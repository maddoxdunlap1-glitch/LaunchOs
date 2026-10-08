#!/bin/bash
set -ex
W=/tmp/claude-0/-home-claude/238c829b-9097-5fd1-973a-842ef65fdfce/scratchpad
cd $W/iso
rm -f image/casper/filesystem.squashfs LaunchOS.iso
mksquashfs root image/casper/filesystem.squashfs -comp zstd -Xcompression-level 10 -b 256K -noappend -e root/boot/vmlinuz-6.8.0-146-generic -e root/boot/initrd.img-6.8.0-146-generic -e root/proc -e root/sys -e root/dev -e root/tmp -e root/run
xorriso -as mkisofs -o LaunchOS.iso -isohybrid-mbr /usr/lib/ISOLINUX/isohdpfx.bin -c isolinux/boot.cat -b isolinux/isolinux.bin -no-emul-boot -boot-load-size 4 -boot-info-table -V LAUNCHOS -J -R image
ls -lh LaunchOS.iso
echo PACK_DONE
