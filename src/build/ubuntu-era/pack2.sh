#!/bin/bash
set -ex
W=/tmp/claude-0/-home-claude/238c829b-9097-5fd1-973a-842ef65fdfce/scratchpad
cd $W/iso
rm -rf root/usr/share/doc/* root/usr/share/man/* root/usr/share/info/* root/var/cache/apt/* root/var/log/*.log root/var/log/apt/*
find root/usr/share/locale -mindepth 1 -maxdepth 1 ! -name 'en*' ! -name 'locale.alias' -exec rm -rf {} +
find root/usr/share/i18n -mindepth 1 -maxdepth 1 -exec rm -rf {} + 2>/dev/null || true
rm -f image/casper/filesystem.squashfs LaunchOS.iso
mksquashfs root image/casper/filesystem.squashfs -comp xz -Xbcj x86 -b 1M -noappend -e root/boot/vmlinuz-6.8.0-146-generic -e root/boot/initrd.img-6.8.0-146-generic -e root/proc -e root/sys -e root/dev -e root/tmp -e root/run
xorriso -as mkisofs -o LaunchOS.iso -isohybrid-mbr /usr/lib/ISOLINUX/isohdpfx.bin -c isolinux/boot.cat -b isolinux/isolinux.bin -no-emul-boot -boot-load-size 4 -boot-info-table -V LAUNCHOS -J -R image
ls -lh LaunchOS.iso
echo PACK2_DONE
