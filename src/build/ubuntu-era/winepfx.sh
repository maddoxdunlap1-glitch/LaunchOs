#!/bin/bash
# Makes Wine's Windows folder for the player ahead of time, so the first program starts fast.
set -x
O=/tmp/claude-0/-home-claude/238c829b-9097-5fd1-973a-842ef65fdfce/scratchpad
R=$O/iso/root
cleanup() { for m in dev/pts dev proc sys run tmp; do umount -l $R/$m 2>/dev/null || true; done; }
trap cleanup EXIT
mount --bind /dev $R/dev; mount --bind /dev/pts $R/dev/pts; mount -t proc proc $R/proc; mount -t sysfs sys $R/sys; mount -t tmpfs tmpfs $R/run; mount -t tmpfs tmpfs $R/tmp
rm -rf $R/home/player/.wine
chroot $R su - player -c "env WINEDLLOVERRIDES='mscoree=;mshtml=' WINEDEBUG=-all DISPLAY= WAYLAND_DISPLAY= wineboot --init; wineserver -w" 2>&1 | tail -5
du -sm $R/home/player/.wine; ls $R/home/player/.wine/drive_c/
echo PFX_DONE
