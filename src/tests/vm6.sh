#!/bin/bash
# vm6.sh MODE [extra qemu args...]   MODE: cd-bios cd-uefi usb-bios usb-uefi disk-bios disk-uefi
# Disks: $O/data.img (save disk, if present and DATA=1), $O/target.qcow2 (install target, if TARGET=1)
O=/tmp/claude-0/-home-claude/238c829b-9097-5fd1-973a-842ef65fdfce/scratchpad
mode=$1; shift
pgrep -x qemu-system-x86 >/dev/null && { echo "a VM is already running"; exit 1; }
cd $O; rm -f ser.sock monb qmp
args=(-m 3072 -smp 2 -cpu qemu64,+sse4.1,+sse4.2,+ssse3,+popcnt -vga std -display none
  -nic user,model=e1000 -audiodev none,id=snd -device intel-hda -device hda-duplex,audiodev=snd
  -usb -device usb-tablet -device usb-ehci,id=ehci
  -monitor unix:$O/monb,server,nowait -qmp unix:$O/qmp,server,nowait -serial unix:$O/ser.sock,server,nowait)
case $mode in
  *-uefi) cp /usr/share/OVMF/OVMF_VARS_4M.fd $O/vars6.fd 2>/dev/null; [ -f $O/vars6.keep ] && cp $O/vars6.keep $O/vars6.fd
          args+=(-M q35 -drive if=pflash,format=raw,readonly=on,file=/usr/share/OVMF/OVMF_CODE_4M.fd -drive if=pflash,format=raw,file=$O/vars6.fd) ;;
  *) args+=(-M pc) ;;
esac
case $mode in
  cd-*) args+=(-drive file=$O/t6.iso,media=cdrom,if=none,id=cd -device ide-cd,drive=cd,bootindex=1) ;;
  usb-*) args+=(-drive file=$O/usb.img,format=raw,if=none,id=stick -device usb-storage,bus=ehci.0,drive=stick,removable=on,bootindex=1) ;;
  disk-*) ;;
esac
[ "$DATA" = 1 ] && args+=(-drive file=$O/data.img,format=raw,if=none,id=data -device ide-hd,drive=data,bus=ide.1)
if [ "$TARGET" = 1 ]; then
  if [ "${mode#disk}" != "$mode" ]; then args+=(-drive file=$O/target.qcow2,if=none,id=tgt -device ide-hd,drive=tgt,bootindex=1)
  else case $mode in *-uefi) tb=",bus=ide.2" ;; *) tb="" ;; esac
       args+=(-drive file=$O/target.qcow2,if=none,id=tgt -device ide-hd,drive=tgt,bootindex=5$tb); fi
fi
setsid nohup qemu-system-x86_64 "${args[@]}" "$@" > $O/qvm.log 2>&1 < /dev/null &
for i in $(seq 1 30); do [ -S $O/ser.sock ] && break; sleep 1; done
echo "VM started ($mode)"
