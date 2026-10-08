#!/bin/bash
set -ex
O=/tmp/claude-0/-home-claude/238c829b-9097-5fd1-973a-842ef65fdfce/scratchpad
cd $O/iso
test "$(mount | grep -c iso/root)" = 0
rm -rf root/var/cache/apt/* root/var/lib/apt/lists/* root/usr/share/doc/* root/usr/share/man/*
cp root/boot/initrd.img-6.8.0-146-generic image/casper/initrd; chmod 644 image/casper/initrd
rm -f image/casper/filesystem.squashfs LaunchOS-plain.iso
mksquashfs root image/casper/filesystem.squashfs -comp xz -Xbcj x86 -b 1M -noappend -no-progress -e root/boot/vmlinuz-6.8.0-146-generic -e root/boot/initrd.img-6.8.0-146-generic -e root/proc -e root/sys -e root/dev -e root/tmp -e root/run
xorriso -as mkisofs -o LaunchOS-plain.iso -V LAUNCHOS -J -joliet-long -R -c boot.catalog \
 -b boot/grub/eltorito.img -no-emul-boot -boot-load-size 4 -boot-info-table --grub2-boot-info \
 -eltorito-alt-boot -e boot/grub/efiboot.img -no-emul-boot -boot-load-size full image
ls -lh LaunchOS-plain.iso
echo B4_DONE
