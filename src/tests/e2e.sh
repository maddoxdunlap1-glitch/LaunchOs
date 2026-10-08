#!/bin/bash
# End-to-end test of the LaunchOS ISO under VirtualBox-like conditions:
# GPU driver forced to fail (no 3D), network, HD Audio, USB tablet. Serial console
# is added to the boot options only, so system state can be checked from outside.
O=/tmp/claude-0/-home-claude/238c829b-9097-5fd1-973a-842ef65fdfce/scratchpad
cd $O/iso || exit 1
cp image/boot/grub/grub.cfg $O/grub.cfg.final
sed -i 's#quiet splash loglevel=0#console=ttyS0,115200 console=tty0 systemd.setenv=MESA_LOADER_DRIVER_OVERRIDE=vmwgfx quiet splash loglevel=0#' image/boot/grub/grub.cfg
rm -f $O/e2e.iso
xorriso -as mkisofs -o $O/e2e.iso -V LAUNCHOS -J -joliet-long -R -c boot.catalog \
  -b boot/grub/eltorito.img -no-emul-boot -boot-load-size 4 -boot-info-table --grub2-boot-info \
  -eltorito-alt-boot -e boot/grub/efiboot.img -no-emul-boot -boot-load-size full image >/dev/null 2>&1
cp $O/grub.cfg.final image/boot/grub/grub.cfg
echo "release boot config untouched: $(grep -c -E 'ttyS0|setenv' image/boot/grub/grub.cfg) test options"

cd $O/www && (setsid nohup python3 -m http.server 8000 --bind 0.0.0.0 > $O/http.log 2>&1 < /dev/null &)
cd $O; rm -f ser.sock ser.sock.log monb e2e-*.ppm
setsid nohup qemu-system-x86_64 -M pc -m 2048 -smp 2 -cpu qemu64 \
  -drive file=$O/e2e.iso,media=cdrom,if=ide,index=2 -boot d -vga std -display none \
  -nic user,model=e1000 -audiodev none,id=snd -device intel-hda -device hda-duplex,audiodev=snd \
  -usb -device usb-tablet \
  -monitor unix:$O/monb,server,nowait -serial unix:$O/ser.sock,server,nowait > qb.log 2>&1 < /dev/null &
sleep 2
shot() { echo "screendump $O/e2e-$1.ppm" | socat - UNIX-CONNECT:$O/monb >/dev/null; }
clean() { sed 's/\x1b\[[0-9;]*[mK]//g' | grep -vE 'DONE_MARK|root@launchos|^\s*$|echo '; }

echo "== 1. boot (waiting for login prompt, then for the launcher to settle)"
timeout 590 python3 $O/sh.py $O/ser.sock 480 'sleep 90; systemctl show-environment | grep MESA; for s in systemd-networkd systemd-resolved launchos-helper.path launcher; do printf "%s=%s " $s $(systemctl is-active $s); done; echo; journalctl -u launcher -b --no-pager -o cat | grep -cE "Unable to create|Could not initialize|Aborting"' | clean | tail -4
for i in $(seq 1 40); do sleep 5; shot probe; v=$(python3 -c "
from PIL import Image
im=Image.open('$O/e2e-probe.ppm').convert('RGB'); r,g,b=im.getpixel((640,60)); print('home' if (r,g,b)!=(0,0,0) and b>r else 'wait')"); [ "$v" = home ] && { echo "home screen showing"; sleep 8; break; }; done
rm -f $O/e2e-probe.ppm
shot 1-home

echo "== 2. browser"
python3 $O/typ.py $O/monb 'KEY:right' 'KEY:ret' 'SLEEP:25'
shot 2-start
python3 $O/typ.py $O/monb 'KEY:ctrl-l' 'SLEEP:1' '10.0.2.2:8000' 'SLEEP:12'
shot 3-page
python3 $O/typ.py $O/monb 'KEY:ctrl-w' 'SLEEP:4'
shot 4-back-home
echo "web server log: $(grep -c 'GET / ' $O/http.log) page request(s)"

echo "== 3. volume and time zone"
python3 $O/sh2.py $O/ser.sock 'amixer -M sget Master | grep -o "\[[0-9]*%\]" | head -1' | clean | tail -1
python3 $O/typ.py $O/monb 'KEY:m' 'SLEEP:3' 'KEY:left' 'SLEEP:2' 'KEY:down' 'KEY:ret' 'SLEEP:2' 'KEY:left' 'KEY:left' 'SLEEP:2' 'KEY:esc' 'KEY:esc' 'SLEEP:2'
python3 $O/sh2.py $O/ser.sock 'amixer -M sget Master | grep -o "\[[0-9]*%\]" | head -1' | clean | tail -1
python3 $O/typ.py $O/monb 'KEY:left' 'KEY:ret' 'SLEEP:6' 'KEY:ret' 'SLEEP:3' 'KEY:ret' 'SLEEP:2' 'KEY:down' 'KEY:down' 'KEY:ret' 'SLEEP:4' 'denv' 'SLEEP:2' 'KEY:ret' 'SLEEP:1' 'KEY:ret' 'SLEEP:5'
shot 5-timezone
python3 $O/sh2.py $O/ser.sock 'timedatectl | grep "Time zone"; ls /run/launchos/' | clean | tail -2

echo "== 4. shut down from the menu"
python3 $O/typ.py $O/monb 'KEY:m' 'SLEEP:7' 'KEY:m' 'SLEEP:3' 'KEY:left' 'SLEEP:2' 'KEY:down' 'KEY:down' 'KEY:down' 'KEY:down' 'KEY:down' 'KEY:down' 'KEY:ret' 'SLEEP:2' 'KEY:ret'
for i in $(seq 1 24); do sleep 5; pgrep -x qemu-system-x86 >/dev/null || { echo "VM turned off about $((i*5))s after Shut down"; break; }; done
pgrep -x qemu-system-x86 >/dev/null && { shot 6-stuck; echo "VM still running after 2 minutes"; }

ps -eo pid,comm,args | awk '$2=="python3" && /http.server/ {print $1}' | xargs -r kill
python3 - <<EOF
from PIL import Image, ImageDraw
import glob, os
fs = sorted(glob.glob('$O/e2e-*.ppm'))
ims = [(os.path.basename(f), Image.open(f).convert('RGB').resize((480, 300))) for f in fs]
c = Image.new('RGB', (970, 320 * ((len(ims) + 1) // 2)), (255, 255, 255))
for k, (n, im) in enumerate(ims):
    x, y = (k % 2) * 490, (k // 2) * 320
    c.paste(im, (x, y)); ImageDraw.Draw(c).text((x + 4, y + 303), n, fill=(200, 0, 0))
c.save('$O/e2e.png')
EOF
echo done
