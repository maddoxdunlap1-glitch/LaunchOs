#!/bin/bash
set -e
O=/tmp/claude-0/-home-claude/238c829b-9097-5fd1-973a-842ef65fdfce/scratchpad
cd $O/iso
cp image/boot/grub/grub.cfg $O/grub.cfg.final
sed -i 's#quiet splash loglevel=0#console=ttyS0,115200 console=tty0 quiet splash loglevel=0#' image/boot/grub/grub.cfg
rm -f $O/e2e.iso
xorriso -as mkisofs -o $O/e2e.iso -V LAUNCHOS -J -joliet-long -R -c boot.catalog \
  -b boot/grub/eltorito.img -no-emul-boot -boot-load-size 4 -boot-info-table --grub2-boot-info \
  -eltorito-alt-boot -e boot/grub/efiboot.img -no-emul-boot -boot-load-size full image >/dev/null 2>&1
cp $O/grub.cfg.final image/boot/grub/grub.cfg
echo "release grub.cfg test lines: $(grep -c ttyS0 image/boot/grub/grub.cfg)"
cd $O/www && (setsid nohup python3 -m http.server 8000 --bind 0.0.0.0 > $O/http.log 2>&1 < /dev/null &)
cd $O; rm -f ser.sock ser.sock.log monb
setsid nohup qemu-system-x86_64 -M pc -m 2048 -smp 2 -cpu qemu64 \
  -drive file=$O/e2e.iso,media=cdrom,if=ide,index=2 -boot d -vga std -display none \
  -nic user,model=e1000 -audiodev none,id=snd -device intel-hda -device hda-duplex,audiodev=snd \
  -usb -device usb-tablet \
  -monitor unix:$O/monb,server,nowait -serial unix:$O/ser.sock,server,nowait > qb.log 2>&1 < /dev/null &
echo started
