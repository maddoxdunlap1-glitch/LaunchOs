#!/bin/bash
set -ex
W=/tmp/claude-0/-home-claude/238c829b-9097-5fd1-973a-842ef65fdfce/scratchpad
export DEBIAN_FRONTEND=noninteractive
grep -rl nodesource /etc/apt/ 2>/dev/null | xargs -r rm -f
apt-get update -qq
apt-get install -y -qq qemu-system-x86 qemu-utils isolinux syslinux-common xorriso squashfs-tools socat rsync unzip python3-pil
cd $W
unzip -o -q /mnt/user-data/outputs/LaunchOS-virtualbox.zip LaunchOS.vdi
qemu-img convert -O raw LaunchOS.vdi disk.raw
rm -f LaunchOS.vdi
mkdir -p mnt iso
L=$(losetup -f --show -o 1048576 disk.raw)
mount -o ro $L mnt
rsync -aH mnt/ iso/root/
umount mnt; losetup -d $L
rm -f disk.raw
du -sm iso/root
echo PREP_DONE
