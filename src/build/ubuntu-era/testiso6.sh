#!/bin/bash
# Test copy of the v0.6 image: serial console + VirtualBox-like graphics failure. Same hybrid layout.
O=/tmp/claude-0/-home-claude/238c829b-9097-5fd1-973a-842ef65fdfce/scratchpad
cd $O/iso || exit 1
cp image/boot/grub/grub.cfg $O/grub.cfg.final
sed -i 's#quiet splash loglevel=0#console=ttyS0,115200 console=tty0 systemd.mask=serial-getty@ttyS0.service systemd.debug_shell=/dev/ttyS0 systemd.setenv=MESA_LOADER_DRIVER_OVERRIDE=vmwgfx quiet splash loglevel=0#' image/boot/grub/grub.cfg
rm -f $O/t6.iso
xorriso -as mkisofs -o $O/t6.iso -V LAUNCHOS -J -joliet-long -R -l -iso-level 3 \
  --grub2-mbr /usr/lib/grub/i386-pc/boot_hybrid.img -partition_offset 16 --mbr-force-bootable \
  -append_partition 2 0xef image/boot/grub/efiboot.img \
  -c boot.catalog -b boot/grub/eltorito.img -no-emul-boot -boot-load-size 4 -boot-info-table --grub2-boot-info \
  -eltorito-alt-boot -e boot/grub/efiboot.img -no-emul-boot -boot-load-size full image >/dev/null 2>&1
cp $O/grub.cfg.final image/boot/grub/grub.cfg
echo "test iso ready; release boot config has $(grep -c -E 'ttyS0|setenv' image/boot/grub/grub.cfg) test options"
