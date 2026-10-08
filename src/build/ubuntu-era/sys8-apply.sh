#!/bin/bash
# Applies the v0.8 changes (terminal, Store, updates) to the OS image.
set -ex
O=/tmp/claude-0/-home-claude/238c829b-9097-5fd1-973a-842ef65fdfce/scratchpad
R=$O/iso/root
cp -a $O/sys6/. $R/
find $R/usr/local -name __pycache__ -prune -exec rm -rf {} +
chmod 755 $R/usr/local/bin/launchos-session $R/usr/local/bin/launchos-inner $R/usr/local/sbin/launchos-*
chmod 644 $R/usr/local/sbin/launchos-status $R/usr/local/lib/launchos/disks.py
# /media/player belongs to root: only root makes the drive folders in it
mkdir -p $R/media/player; chown 0:0 $R/media/player; chmod 755 $R/media/player
rm -rf $R/opt/launcher; mkdir -p $R/opt/launcher
cp -a $O/ui/. $R/opt/launcher/
rm -rf $R/opt/launcher/__pycache__
chown -R 0:0 $R/opt/launcher; chmod -R a+rX,go-w $R/opt/launcher
sed -i 's/^VERSION=.*/VERSION="0.8"/; s/^BUILD_DATE=.*/BUILD_DATE="'$(date -u +%F)'"/' $R/etc/launchos-release
chroot $R systemctl enable launchos-helper.path >/dev/null 2>&1 || true
chroot $R systemctl enable launchos-reconcile.service >/dev/null 2>&1 || true
chmod 644 $R/etc/launchos/update.conf
# no fixed root password any more: set an admin password in Settings, then use sudo
chroot $R passwd -l root >/dev/null
chroot $R sh -c 'awk -F: "\$1==\"root\"{print substr(\$2,1,1)}" /etc/shadow'
ls -la $R/etc/systemd/system/sysinit.target.wants/ | grep launchos
cat $R/etc/launchos-release
ls -la $R/opt/launcher $R/media
