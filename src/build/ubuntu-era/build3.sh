#!/bin/bash
set -ex
W=/tmp/claude-0/-home-claude/238c829b-9097-5fd1-973a-842ef65fdfce/scratchpad
cd $W/iso
test "$(mount | grep -c iso/root)" = 0
ARGS="boot=casper quiet splash loglevel=0 rd.systemd.show_status=false systemd.show_status=false udev.log_level=3 vt.global_cursor_default=0 nowatchdog username=player hostname=launchos"
cat > image/isolinux/isolinux.cfg <<C
DEFAULT live
PROMPT 0
TIMEOUT 1
LABEL live
  KERNEL /casper/vmlinuz
  APPEND initrd=/casper/initrd $ARGS
C
mkdir -p image/boot/grub
cat > image/boot/grub/grub.cfg <<C
set timeout=0
set default=0
menuentry "LaunchOS" {
  linux /casper/vmlinuz $ARGS
  initrd /casper/initrd
}
C
cat > embed.cfg <<'C'
search --no-floppy --set=root --file /casper/vmlinuz
set prefix=($root)/boot/grub
configfile ($root)/boot/grub/grub.cfg
C
grub-mkstandalone -O x86_64-efi --modules="part_gpt part_msdos iso9660 search search_fs_file linux normal configfile all_video efi_gop" --locales="" --fonts="" --themes="" -o bootx64.efi "boot/grub/grub.cfg=embed.cfg"
rm -f image/boot/grub/efiboot.img
dd if=/dev/zero of=image/boot/grub/efiboot.img bs=1M count=6 status=none
mkfs.vfat -n EFIBOOT image/boot/grub/efiboot.img >/dev/null
mmd -i image/boot/grub/efiboot.img ::/EFI ::/EFI/BOOT
mcopy -i image/boot/grub/efiboot.img bootx64.efi ::/EFI/BOOT/BOOTX64.EFI
rm -f image/casper/filesystem.squashfs LaunchOS.iso
mksquashfs root image/casper/filesystem.squashfs -comp xz -Xbcj x86 -b 1M -noappend -no-progress -e root/boot/vmlinuz-6.8.0-146-generic -e root/boot/initrd.img-6.8.0-146-generic -e root/proc -e root/sys -e root/dev -e root/tmp -e root/run
xorriso -as mkisofs -o LaunchOS.iso -V LAUNCHOS -J -R \
  -isohybrid-mbr /usr/lib/ISOLINUX/isohdpfx.bin \
  -c isolinux/boot.cat -b isolinux/isolinux.bin -no-emul-boot -boot-load-size 4 -boot-info-table \
  -eltorito-alt-boot -e boot/grub/efiboot.img -no-emul-boot -isohybrid-gpt-basdat image
ls -lh LaunchOS.iso
echo B3_DONE
