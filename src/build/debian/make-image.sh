#!/bin/bash
# Builds the LaunchOS ISO: the Debian base (base.sh) plus LaunchOS's own files from src/.
# One image that boots as a disc and from a USB stick (written with Etcher, or Rufus in DD
# mode), on BIOS and UEFI PCs.
#
#   sudo ./make-image.sh BASE.squashfs WORKDIR VERSION [fast]
#     -> WORKDIR/LaunchOS.iso        ("fast": quicker, larger compression for test builds)
#
# boot-order.txt (next to this script, made by the start-up test in tests/ci_boot.py) lists the
# files LaunchOS reads while starting; they go first in the image so a USB stick reads them in
# one sweep instead of jumping around.
#
# The unpacked base is kept in WORKDIR/root between runs and reused while BASE.squashfs is the
# same, so trying a change takes minutes; a release build should start from an empty WORKDIR.
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
SRC=$(cd "$HERE/../.." && pwd)
BASE=$(realpath "${1:?usage: make-image.sh BASE.squashfs WORKDIR VERSION [fast]}")
W=$(realpath -m "${2:?}")
VERSION=${3:?}
FAST=${4:-}
R=$W/root
IMG=$W/image
mkdir -p "$W"

# ---------- the base system ----------
sum=$(stat -c '%s %Y' "$BASE")
if [ ! -d "$R" ] || [ "$(cat "$W/base.stamp" 2>/dev/null)" != "$sum" ]; then
  rm -rf "$R"
  unsquashfs -q -d "$R" "$BASE"
  echo "$sum" > "$W/base.stamp"
fi

cleanup() { for m in dev/pts dev proc sys run; do umount -l "$R/$m" 2>/dev/null || true; done; }
trap cleanup EXIT
mount --bind /dev "$R/dev"; mount --bind /dev/pts "$R/dev/pts"
mount -t proc proc "$R/proc"; mount -t sysfs sys "$R/sys"; mount -t tmpfs tmpfs "$R/run"
IN="chroot $R env LANG=C.UTF-8"

# ---------- LaunchOS's files ----------
cp -a "$SRC/rootfs/." "$R/"
find "$R/usr/local" -name __pycache__ -prune -exec rm -rf {} +
chown -R 0:0 "$R/usr/local" "$R/etc/launchos" "$R/etc/systemd/system" "$R/etc/initramfs-tools"
chmod 755 "$R/usr/local/bin/launchos-session" "$R/usr/local/bin/launchos-inner" "$R"/usr/local/sbin/launchos-* \
  "$R/usr/local/lib/launchos/steam-shim/zenity" "$R/etc/initramfs-tools/hooks/launchos-saving" \
  "$R/etc/initramfs-tools/scripts/live-premount/launchos-saving"
chmod 644 "$R/usr/local/sbin/launchos-status" "$R/usr/local/lib/launchos/disks.py" "$R/etc/launchos/update.conf" "$R/etc/launchos/pro.conf"
# /media/player belongs to root: only root makes the drive folders in it
mkdir -p "$R/media/player"; chown 0:0 "$R/media/player"; chmod 755 "$R/media/player"
rm -rf "$R/opt/launcher"; mkdir -p "$R/opt/launcher"
cp -a "$SRC/ui/." "$R/opt/launcher/"
find "$R/opt/launcher" -name __pycache__ -prune -exec rm -rf {} +
# compiled ahead of time: the launcher's own modules start without compiling (it can't write here)
python3 -m compileall -q "$R/opt/launcher" >/dev/null 2>&1 || true
$IN python3 -m compileall -q /opt/launcher >/dev/null 2>&1 || true
chown -R 0:0 "$R/opt/launcher"; chmod -R a+rX,go-w "$R/opt/launcher"
sed -i "s/^VERSION=.*/VERSION=\"$VERSION\"/; s/^BUILD_DATE=.*/BUILD_DATE=\"$(date -u +%F)\"/" "$R/etc/launchos-release"
cat "$R/etc/launchos-release"

# boot screen: the ferris wheel
rm -rf "$R/usr/share/plymouth/themes/launchos"
cp -a "$SRC/boot-theme/plymouth-launchos" "$R/usr/share/plymouth/themes/launchos"
chown -R 0:0 "$R/usr/share/plymouth/themes/launchos"
$IN plymouth-set-default-theme launchos

# services: the launcher on tty1 (no login prompt there), a text console on tty2
$IN systemctl set-default graphical.target
for u in launcher.service launchos-helper.path launchos-reconcile.service launchos-audio.service launchos-pro-check.timer \
         iwd.service seatd.service systemd-networkd.service systemd-resolved.service systemd-timesyncd.service getty@tty2.service; do
  $IN systemctl enable "$u" >/dev/null 2>&1 || echo "note: couldn't enable $u"
done
for u in getty@tty1.service systemd-networkd-wait-online.service apt-daily.timer apt-daily-upgrade.timer e2scrub_all.timer; do
  $IN systemctl mask "$u" >/dev/null 2>&1 || true
done
# the player's groups (seat access, sound, Wi-Fi) in case the base predates a change
$IN groupadd -f netdev
$IN usermod -aG audio,video,input,render,netdev player
$IN passwd -l root >/dev/null

# font cache made now, not on first start (the Terminal's first window waits for it)
$IN fc-cache -s >/dev/null 2>&1 || true

# start-up image with the live system and the LaunchOS boot screen
KVER=$(ls "$R/lib/modules" | sort -V | tail -1)
$IN update-initramfs -u -k "$KVER"
# A small start-up image loads and unpacks in a fraction of the time: the big AMD and NVIDIA
# graphics drivers and their firmware (about 140 MB) come out of it. They load from the system a
# few seconds later; until then the boot animation uses the screen the firmware (or GRUB) set up.
# Intel graphics, virtual machine graphics and everything that finds the disc or USB stick stay.
cat > "$R/tmp/slim-initrd" <<'SLIM'
#!/bin/sh
set -e
K=$1; I=/boot/initrd.img-$K; T=/tmp/initrd-slim
rm -rf "$T"; mkdir -p "$T"
unmkinitramfs "$I" "$T"
M=$T/main/usr/lib/modules/$K/kernel/drivers/gpu/drm
F=$T/main/usr/lib/firmware
rm -rf "$M/amd" "$M/nouveau" "$M/radeon" "$F/amdgpu" "$F/nvidia" "$F/radeon"
# network cards aren't needed to start from a disc, USB stick or drive; nor is udev's hardware list
rm -rf "$T/main/usr/lib/modules/$K/kernel/drivers/net" "$T/main/usr/lib/modules/$K/kernel/drivers/infiniband" "$T/main/usr/lib/udev/hwdb.bin"
depmod -a -b "$T/main" "$K"
: > "$I.new"
for e in "$T"/early*; do
  [ -d "$e" ] && ( cd "$e" && find . -print0 | LC_ALL=C sort -z | cpio --null -o -H newc --quiet ) >> "$I.new"
done
( cd "$T/main" && find . -print0 | LC_ALL=C sort -z | cpio --null -o -H newc --quiet | zstd -q -19 -T0 ) >> "$I.new"
mv "$I.new" "$I"
rm -rf "$T"
SLIM
chmod 755 "$R/tmp/slim-initrd"
ls -l "$R/boot/initrd.img-$KVER"
$IN /tmp/slim-initrd "$KVER"
rm -f "$R/tmp/slim-initrd"
ls -l "$R/boot/initrd.img-$KVER"
cleanup
trap - EXIT

# ---------- the disc image ----------
rm -rf "$IMG"; mkdir -p "$IMG/live" "$IMG/boot/grub" "$IMG/EFI/BOOT"
cp "$R/boot/vmlinuz-$KVER" "$IMG/live/vmlinuz"
cp "$R/boot/initrd.img-$KVER" "$IMG/live/initrd.img"
# quickusbmodules: live-boot otherwise waits 5 seconds for USB drives that are already there
ARGS="boot=live persistence quickusbmodules quiet splash loglevel=0 rd.systemd.show_status=false systemd.show_status=false udev.log_level=3 vt.global_cursor_default=0 nowatchdog"
cat > "$IMG/boot/grub/grub.cfg" <<EOF
set timeout=0
set default=0
# BIOS PCs: start Linux with a graphics screen, so the boot animation shows from the start
# (UEFI PCs always have one)
if [ "\$grub_platform" = "pc" ]; then
  insmod all_video
  set gfxpayload=auto
fi

# LaunchOS is 64-bit. On a 32-bit virtual machine, explain the fix instead of stopping silently.
if [ "\$grub_platform" = "pc" ]; then
  insmod cpuid
  insmod sleep
  insmod halt
  if ! cpuid -l; then
    echo ""
    echo "  LaunchOS needs a 64-bit virtual machine."
    echo ""
    echo "  This VM is set up as 32-bit, so LaunchOS can't start."
    echo "  In VirtualBox, power off the VM and open Settings:"
    echo "    General:  Type = Linux, Version = Debian (64-bit)"
    echo "    System:   Base Memory = 2048 MB or more"
    echo ""
    echo "  Or add the ready-made LaunchOS.vbox with Machine > Add."
    echo ""
    sleep -i 99999
    halt
  fi
fi

menuentry "LaunchOS" {
  linux /live/vmlinuz $ARGS
  initrd /live/initrd.img
}
EOF
# Boot loaders (Debian's GRUB). Both find the system by looking for /live/vmlinuz.
cat > "$W/embed.cfg" <<'EOF'
search --no-floppy --set=root --file /live/vmlinuz
set prefix=($root)/boot/grub
configfile ($root)/boot/grub/grub.cfg
EOF
G=$R/usr/lib/grub
grub-mkimage -d "$G/i386-pc" -O i386-pc-eltorito -p /boot/grub -c "$W/embed.cfg" -o "$IMG/boot/grub/eltorito.img" \
  biosdisk iso9660 part_msdos part_gpt fat ext2 search search_fs_file normal configfile linux echo test cpuid sleep halt all_video
grub-mkstandalone -d "$G/x86_64-efi" -O x86_64-efi \
  --modules="part_gpt part_msdos iso9660 fat ext2 search search_fs_file linux normal configfile all_video efi_gop" \
  --locales="" --fonts="" --themes="" -o "$W/bootx64.efi" "boot/grub/grub.cfg=$W/embed.cfg"
cp "$W/bootx64.efi" "$IMG/EFI/BOOT/BOOTX64.EFI"
rm -f "$IMG/boot/grub/efiboot.img"
dd if=/dev/zero of="$IMG/boot/grub/efiboot.img" bs=1M count=6 status=none
mkfs.vfat -n EFIBOOT "$IMG/boot/grub/efiboot.img" >/dev/null
mmd -i "$IMG/boot/grub/efiboot.img" ::/EFI ::/EFI/BOOT
mcopy -i "$IMG/boot/grub/efiboot.img" "$W/bootx64.efi" ::/EFI/BOOT/BOOTX64.EFI

# Compression: zstd unpacks several times faster than xz, which matters more for start-up time
# than the slightly bigger image. SQUASH=xz gives the smallest image.
case "${SQUASH:-zstd}" in
  xz) COMP=(-comp xz -Xbcj x86 -b 1M) ;;
  *)  COMP=(-comp zstd -Xcompression-level 19 -b 256K) ;;
esac
[ "$FAST" = fast ] && COMP=(-comp zstd -Xcompression-level 6 -b 256K)
# the files read while starting go first (highest priority first), in the order they're listed
SORT=()
if [ -s "$HERE/boot-order.txt" ]; then
  python3 - "$HERE/boot-order.txt" "$R" > "$W/sort.txt" <<'PY'
import os, stat, sys
listing, root = sys.argv[1], sys.argv[2]
p = 32000
for line in open(listing, encoding='utf-8', errors='replace'):
    f = line.rstrip('\n')
    if not f or f.startswith('#'):
        continue
    f = f[2:] if f.startswith('./') else f.lstrip('/')
    if any(c.isspace() for c in f) or '..' in f.split('/'):
        continue   # (the sort list can't hold names with spaces)
    try:
        if not stat.S_ISREG(os.lstat(os.path.join(root, f)).st_mode):
            continue
    except OSError:
        continue
    print(f, p)
    p -= 1
    if p < -32000:
        break
PY
  echo "start-up files first: $(wc -l < "$W/sort.txt")"
  SORT=(-sort "$W/sort.txt")
fi
mksquashfs "$R" "$IMG/live/filesystem.squashfs" "${COMP[@]}" "${SORT[@]}" -noappend -no-progress \
  -wildcards -e 'proc/*' 'sys/*' 'dev/*' 'run/*' 'tmp/*'
ls -l "$IMG/live/filesystem.squashfs"

rm -f "$W/LaunchOS.iso"
xorriso -as mkisofs -o "$W/LaunchOS.iso" -V LAUNCHOS -A "LAUNCHOS $VERSION" -publisher LAUNCHOS -J -joliet-long -R -l -iso-level 3 \
  --grub2-mbr "$G/i386-pc/boot_hybrid.img" -partition_offset 16 --mbr-force-bootable \
  -append_partition 2 0xef "$IMG/boot/grub/efiboot.img" \
  -c boot.catalog -b boot/grub/eltorito.img -no-emul-boot -boot-load-size 4 -boot-info-table --grub2-boot-info \
  -eltorito-alt-boot -e boot/grub/efiboot.img -no-emul-boot -boot-load-size full "$IMG"
ls -lh "$W/LaunchOS.iso"
