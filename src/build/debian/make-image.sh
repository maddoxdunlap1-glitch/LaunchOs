#!/bin/bash
# Builds the LaunchOS ISO: the Debian base (base.sh) plus LaunchOS's own files from src/.
# One image that boots as a disc and from a USB stick (written with Etcher, or Rufus in DD
# mode), on BIOS and UEFI PCs.
#
#   sudo ./make-image.sh BASE.squashfs WORKDIR VERSION [fast]
#     -> WORKDIR/LaunchOS.iso        ("fast": quicker, larger compression for test builds)
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
chmod 644 "$R/usr/local/sbin/launchos-status" "$R/usr/local/lib/launchos/disks.py" "$R/etc/launchos/update.conf"
# /media/player belongs to root: only root makes the drive folders in it
mkdir -p "$R/media/player"; chown 0:0 "$R/media/player"; chmod 755 "$R/media/player"
rm -rf "$R/opt/launcher"; mkdir -p "$R/opt/launcher"
cp -a "$SRC/ui/." "$R/opt/launcher/"
find "$R/opt/launcher" -name __pycache__ -prune -exec rm -rf {} +
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
for u in launcher.service launchos-helper.path launchos-reconcile.service launchos-audio.service \
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

# start-up image with the live system and the LaunchOS boot screen
KVER=$(ls "$R/lib/modules" | sort -V | tail -1)
$IN update-initramfs -u -k "$KVER"
cleanup
trap - EXIT

# ---------- the disc image ----------
rm -rf "$IMG"; mkdir -p "$IMG/live" "$IMG/boot/grub" "$IMG/EFI/BOOT"
cp "$R/boot/vmlinuz-$KVER" "$IMG/live/vmlinuz"
cp "$R/boot/initrd.img-$KVER" "$IMG/live/initrd.img"
ARGS="boot=live persistence quiet splash loglevel=0 rd.systemd.show_status=false systemd.show_status=false udev.log_level=3 vt.global_cursor_default=0 nowatchdog"
cat > "$IMG/boot/grub/grub.cfg" <<EOF
set timeout=0
set default=0

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
  biosdisk iso9660 part_msdos part_gpt fat ext2 search search_fs_file normal configfile linux echo test cpuid sleep halt
grub-mkstandalone -d "$G/x86_64-efi" -O x86_64-efi \
  --modules="part_gpt part_msdos iso9660 fat ext2 search search_fs_file linux normal configfile all_video efi_gop" \
  --locales="" --fonts="" --themes="" -o "$W/bootx64.efi" "boot/grub/grub.cfg=$W/embed.cfg"
cp "$W/bootx64.efi" "$IMG/EFI/BOOT/BOOTX64.EFI"
rm -f "$IMG/boot/grub/efiboot.img"
dd if=/dev/zero of="$IMG/boot/grub/efiboot.img" bs=1M count=6 status=none
mkfs.vfat -n EFIBOOT "$IMG/boot/grub/efiboot.img" >/dev/null
mmd -i "$IMG/boot/grub/efiboot.img" ::/EFI ::/EFI/BOOT
mcopy -i "$IMG/boot/grub/efiboot.img" "$W/bootx64.efi" ::/EFI/BOOT/BOOTX64.EFI

if [ "$FAST" = fast ]; then COMP=(-comp zstd -Xcompression-level 6); else COMP=(-comp xz -Xbcj x86); fi
mksquashfs "$R" "$IMG/live/filesystem.squashfs" "${COMP[@]}" -b 1M -noappend -no-progress \
  -wildcards -e 'proc/*' 'sys/*' 'dev/*' 'run/*' 'tmp/*'
ls -l "$IMG/live/filesystem.squashfs"

rm -f "$W/LaunchOS.iso"
xorriso -as mkisofs -o "$W/LaunchOS.iso" -V LAUNCHOS -J -joliet-long -R -l -iso-level 3 \
  --grub2-mbr "$G/i386-pc/boot_hybrid.img" -partition_offset 16 --mbr-force-bootable \
  -append_partition 2 0xef "$IMG/boot/grub/efiboot.img" \
  -c boot.catalog -b boot/grub/eltorito.img -no-emul-boot -boot-load-size 4 -boot-info-table --grub2-boot-info \
  -eltorito-alt-boot -e boot/grub/efiboot.img -no-emul-boot -boot-load-size full "$IMG"
ls -lh "$W/LaunchOS.iso"
