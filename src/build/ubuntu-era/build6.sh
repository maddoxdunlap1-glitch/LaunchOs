#!/bin/bash
# LaunchOS v0.6 image: one file that boots as a disc (VirtualBox, BIOS + UEFI) and,
# written to a USB stick with Etcher or Rufus (DD mode), from USB (BIOS + UEFI).
set -ex
O=/tmp/claude-0/-home-claude/238c829b-9097-5fd1-973a-842ef65fdfce/scratchpad
cd $O/iso
test "$(mount | grep -c iso/root)" = 0
rm -rf root/var/cache/apt/* root/var/lib/apt/lists/* root/usr/share/doc/* root/usr/share/man/* root/tmp/* root/var/tmp/*
KVER=$(ls root/lib/modules | sort -V | tail -1)
cp root/boot/initrd.img-$KVER image/casper/initrd; chmod 644 image/casper/initrd
cp root/boot/vmlinuz-$KVER image/casper/vmlinuz; chmod 644 image/casper/vmlinuz

# Boot options: saving (casper "persistent") is on whenever a casper-rw disk/partition exists.
grep -q ' persistent ' image/boot/grub/grub.cfg || sed -i 's#boot=casper #boot=casper persistent #' image/boot/grub/grub.cfg
grep -c persistent image/boot/grub/grub.cfg

# Boot loaders. Both find the system by looking for /casper/vmlinuz, on a disc, a USB stick
# written as an image, or a USB stick Rufus filled with files (FAT).
cat > embed.cfg <<'EOF'
search --no-floppy --set=root --file /casper/vmlinuz
set prefix=($root)/boot/grub
configfile ($root)/boot/grub/grub.cfg
EOF
grub-mkimage -O i386-pc-eltorito -p /boot/grub -c embed.cfg -o image/boot/grub/eltorito.img \
  biosdisk iso9660 part_msdos part_gpt fat ext2 search search_fs_file normal configfile linux echo test cpuid sleep halt
grub-mkstandalone -O x86_64-efi --modules="part_gpt part_msdos iso9660 fat ext2 search search_fs_file linux normal configfile all_video efi_gop" \
  --locales="" --fonts="" --themes="" -o bootx64.efi "boot/grub/grub.cfg=embed.cfg"
rm -f image/boot/grub/efiboot.img
dd if=/dev/zero of=image/boot/grub/efiboot.img bs=1M count=6 status=none
mkfs.vfat -n EFIBOOT image/boot/grub/efiboot.img >/dev/null
mmd -i image/boot/grub/efiboot.img ::/EFI ::/EFI/BOOT
mcopy -i image/boot/grub/efiboot.img bootx64.efi ::/EFI/BOOT/BOOTX64.EFI
mkdir -p image/EFI/BOOT && cp bootx64.efi image/EFI/BOOT/BOOTX64.EFI

rm -f image/casper/filesystem.squashfs LaunchOS-plain.iso
mksquashfs root image/casper/filesystem.squashfs -comp xz -Xbcj x86 -b 1M -noappend -no-progress \
  -e root/boot/vmlinuz-$KVER -e root/boot/initrd.img-$KVER -e root/proc -e root/sys -e root/dev -e root/tmp -e root/run
printf "%s" "$(du -sx --block-size=1 root | cut -f1)" > image/casper/filesystem.size

xorriso -as mkisofs -o LaunchOS-plain.iso -V LAUNCHOS -J -joliet-long -R -l -iso-level 3 \
  --grub2-mbr /usr/lib/grub/i386-pc/boot_hybrid.img -partition_offset 16 --mbr-force-bootable \
  -append_partition 2 0xef image/boot/grub/efiboot.img \
  -c boot.catalog -b boot/grub/eltorito.img -no-emul-boot -boot-load-size 4 -boot-info-table --grub2-boot-info \
  -eltorito-alt-boot -e boot/grub/efiboot.img -no-emul-boot -boot-load-size full image
ls -lh LaunchOS-plain.iso
fdisk -l LaunchOS-plain.iso | tail -4
echo B6_DONE
