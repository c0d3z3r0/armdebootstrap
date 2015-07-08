__author__ = 'Michael Niewöhner <c0d3z3r0>'
__email__ = 'mniewoeh@stud.hs-offenburg.de'

import os
import sys
import time
import re
import subprocess as su
import colorama as co
import tempfile as tm
import operator
import shutil as sh


class ArmDeboostrap:
    sdcard = str
    tmp = str
    name = str
    tools = []
    hostname = str
    partitions = []
    packages = []
    debug = False


    def __init__(self, name, hostname, sdcard, partitions, packages,
                 rootpass='toor', debug=False):
        self.name = name
        self.hostname = hostname
        self.sdcard = sdcard
        self.partitions = partitions
        self.rootpass = rootpass
        self.debug = debug

        # Standard packages and additional packages
        self.packages = packages + \
            ["aptitude", "apt-transport-https", "openssh-server",
             "cpufrequtils", "cpufreqd", "ntp", "tzdata", "htop",
             "locales", "console-setup", "console-data", "vim", "psmisc",
             "keyboard-configuration", "ca-certificates", "dbus", "curl"
             ]


    def logwrite(self, text):
        log = open(self.name + ".log", "a")
        log.write(text + "\n")
        log.close()


    def lprint(self, p):
        print(p)
        self.logwrite(p)


    def print_err(self, error):
        self.lprint(co.Fore.RED + """\
***********************************************
* Error! Please check the following messages! *
*         Your system will NOT boot!          *
***********************************************

""" + error + "\n")


    def print_warn(self, warning):
        self.lprint(co.Fore.YELLOW + warning + co.Fore.RESET)

    def run(self, command, out=0, quit=1):
        if self.debug:
            print(co.Fore.YELLOW + "$: " + command + co.Fore.RESET)
        if out:
            ret = su.Popen(command, shell=True, stderr=su.PIPE)
            success = not ret.wait()
            error = ret.stderr.read().decode()
        else:
            ret = su.getstatusoutput(command)
            success = not ret[0]
            error = ret[1]
            self.logwrite(error + "\n")

        if quit and not success:
            self.print_err(error)
            try:
                sys.exit(1)
            except OSError:
                pass
        else:
            return success


    def checkdep(self):
        tools = [("mkfs.msdos", "dosfstools"),
                 ("cdebootstrap", "cdebootstrap"),
                 ("curl", "curl"),
                 ("fdisk", "fdisk"),
                 ("sed", "sed"),
                 ("qemu-arm-static", "qemu-user-static"),
                 ("fuser", "psmisc"),
                 ]
        missing = []
        for t in tools:
            self.run("which %s" % t[0], quit=0) or missing.append(t[1])
        if missing:
            self.print_err("Missing dependencies: %s.\n"
                           "Install them using `aptitude install %s`."
                           % (', '.join(missing), ' '.join(missing)))
            sys.exit(1)


    def partition(self, p):
        if re.match("^/dev/mmcblk[0-9]+$", self.sdcard):
            return "p" + str(self.partitions.index(p)+1)
        else:
            return str(self.partitions.index(p)+1)


    # TODO: change fdisk to sfdisk or parted
    def createparts(self):
        self.lprint("Delete MBR and partition table and create a new one.")
        cmds = ['o']
        for p in self.partitions:
            num = self.partitions.index(p)+1
            if num > 1:
                cmds += ['n', 'p', '', p['start'], p['end'], 't', str(num),
                         p['type']]
            else:
                cmds += ['n', 'p', '', p['start'], p['end'], 't', p['type']]
        cmds += 'w'
        cmds = ('echo ' + '; echo '.join(cmds))
        self.run("umount -f %s*" % self.sdcard, quit=0)
        self.run('(' + cmds + ') | fdisk %s' % self.sdcard)
        time.sleep(3)  # wait for the system to detect the new partitions


    def formatparts(self):
        self.lprint("Create filesystems.")
        for p in self.partitions:
            if 'ext' in p['fs']:
                self.run("mkfs.%s -F %s%s" % (str(p['fs']), self.sdcard,
                         self.partition(p)))
            elif p['fs'] == 'msdos':
                self.run("mkfs.msdos %s%s" % (self.sdcard, self.partition(p)))


    def mountparts(self):
        self.lprint("Mount filesystems.")
        for p in sorted(self.partitions, key=operator.itemgetter('mount')):
            if p['mount']:  # not swap
                mnt = self.tmp + p['mount']
                if not os.path.isdir(mnt):
                    os.mkdir(mnt, 755)
                self.run("mount %s%s %s" %
                         (self.sdcard, self.partition(p), mnt))


    def unmountparts(self):
        for p in sorted(self.partitions, key=operator.itemgetter('mount'),
                        reverse=True):
            if p['mount']:  # not swap
                mnt = self.tmp + p['mount']
                self.run("umount -f %s%s" % (self.sdcard, self.partition(p)))


    def debootstrap(self):
        self.lprint("Install debian. First stage. "
                    "This will take some minutes.")
        self.run("cdebootstrap --arch=armhf -f standard --foreign jessie "
                 "--include=%s %s" % (','.join(self.packages), self.tmp))

        self.lprint("Second stage. Again, please wait some minutes.")
        self.print_warn("You can safely ignore the perl and locale warnings.")
        sh.copy2("/usr/bin/qemu-arm-static", "%s/usr/bin/qemu-arm-static" %
                 self.tmp)
        self.run("chroot %s /sbin/cdebootstrap-foreign" % self.tmp)
        self.run("chroot %s dpkg-reconfigure locales console-setup "
                 "console-data keyboard-configuration tzdata" %
                 self.tmp, out=1)


    def cleanup(self):
        self.lprint("Unmount and cleanup.")
        self.run("fuser -k %s" % self.tmp, quit=0)
        self.unmountparts()
        os.rmdir(self.tmp)
        self.lprint(co.Fore.GREEN +
                    "OK, that's it. Put the sdcard into your device and power "
                    "it up.\nThe root password is 'toor'." + co.Fore.RESET)


    def writeFile(self, file, content, append=False):
        f = open("%s%s" % (self.tmp, file),
                 {True: 'a', False: 'w'}[append])
        print(content, file=f)
        f.close()


    def configure(self):
        self.lprint("Configure the system.")

        # TODO: make more beautiful with string mask (spaces)
        # fstab
        self.writeFile('/etc/fstab', "proc /proc proc defaults 0 0")

        parts = sorted(self.partitions, key=operator.itemgetter('mount'))
        for p in parts:
            if p['fs'] == 'msdos':
                fs = 'vfat'
            else:
                fs = p['fs']
            if 'ext' in p['fs']:
                opt = 'defaults,noatime'
            else:
                opt = 'defaults'
            self.writeFile('/etc/fstab', "/dev/mmcblk0p%s %s %s %s 0 %s" %
                           (str(self.partitions.index(p)+1), p['mount'], fs,
                            opt, str(parts.index(p)+1)), append=True)


        # Configure networking
        self.writeFile('/etc/network/interfaces', """\
auto eth0
iface eth0 inet dhcp\
        """)

        # Set Hostname
        self.writeFile('/etc/hostname', self.hostname)
        self.writeFile('/etc/hosts', '127.0.0.1 ' + self.hostname, append=True)

        # Change DHCP timeout because we get stuck at boot if
        # there is no network
        self.run("sed -i'' 's/#timeout.*;/timeout 10;/' "
                 "%s/etc/dhcp/dhclient.conf" % self.tmp)

        # Enable SSH PasswordAuthentication and root login
        self.run("sed -i'' 's/without-password/yes/' %s/etc/ssh/sshd_config" %
                 self.tmp)
        self.run("sed -i'' 's/#PasswordAuth/PasswordAuth/' "
                 "%s/etc/ssh/sshd_config" % self.tmp)

        # Fix missing display-manager.service
        self.run("chroot %s systemctl disable display-manager.service" %
                 self.tmp)

        # Set up default root password
        self.run("echo 'echo root:%s | chpasswd' | chroot %s" %
                 (self.rootpass, self.tmp))

        # Add APT sources
        self.writeFile('/etc/apt/sources.list', """\
deb http://ftp.de.debian.org/debian/ jessie main contrib non-free
deb-src http://ftp.de.debian.org/debian/ jessie main contrib non-free

deb http://security.debian.org/ jessie/updates main contrib non-free
deb-src http://security.debian.org/ jessie/updates main contrib non-free

deb http://ftp.de.debian.org/debian jessie-updates main contrib non-free
deb-src http://ftp.de.debian.org/debian jessie-updates main contrib non-free

deb http://ftp.de.debian.org/debian jessie-proposed-updates main contrib non-free
deb-src http://ftp.de.debian.org/debian jessie-proposed-updates main contrib non-free

deb http://ftp.debian.org/debian/ jessie-backports main contrib non-free
deb-src http://ftp.debian.org/debian/ jessie-backports main contrib non-free\
        """)


    def update(self):
        # Update & Upgrade
        self.lprint("Update the system.")
        self.run("chroot %s aptitude -y update" % self.tmp)
        self.run("chroot %s aptitude -y upgrade" % self.tmp)


    def install(self):
        self.createparts()
        self.formatparts()
        self.mountparts()
        self.debootstrap()
        self.configure()
        self.update()


    def init(self):
        co.init()
        self.logwrite("\n\n" + time.strftime("%c"))

        self.lprint("Welcome to " + self.name + "!")

        if os.geteuid():
            self.print_err("You need to run this as root!")
            sys.exit(1)

        self.checkdep()

        if not re.match("^/dev/((h|s)d[a-z]+|mmcblk[0-9]+)$", self.sdcard):
            self.print_err("Wrong sdcard format! Should be in the form"
                           "/dev/[hdX|sdX|mmcblkX] eg. /dev/sda or"
                           "/dev/mmcblk0")
            sys.exit(1)

        if not os.path.exists(self.sdcard):
            self.print_err("SD card path does not exist.")
            sys.exit(1)

        self.lprint(co.Fore.RED + "This is your last chance to abort!" +
                    co.Fore.RESET)
        self.print_warn("Your sdcard is %s. Is that right? [yN] "
                        % self.sdcard)
        if input() is not "y":
            self.lprint("OK. Aborting ...")
            sys.exit(0)

        self.tmp = tm.mkdtemp()
