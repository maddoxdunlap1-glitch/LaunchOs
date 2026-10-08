#!/bin/bash
set -ex
W=/tmp/claude-0/-home-claude/238c829b-9097-5fd1-973a-842ef65fdfce/scratchpad
cd $W/iso; T=$PWD/root
rm -f $T/etc/resolv.conf; cp /etc/resolv.conf $T/etc/resolv.conf
for d in proc sys dev dev/pts; do mount --bind /$d $T/$d; done
trap 'for d in dev/pts dev sys proc; do umount $T/$d 2>/dev/null; done' EXIT
chroot $T /bin/bash -c "export DEBIAN_FRONTEND=noninteractive http_proxy=$http_proxy https_proxy=$https_proxy HTTPS_PROXY=$HTTPS_PROXY HTTP_PROXY=$HTTP_PROXY; apt-get update -qq; apt-get install -y -qq --no-install-recommends casper; apt-get clean; rm -rf /var/lib/apt/lists/*"
sed -i 's/^export USERNAME=.*/export USERNAME="player"/; s/^export USERFULLNAME=.*/export USERFULLNAME="Player"/; s/^export HOST=.*/export HOST="launchos"/' $T/etc/casper.conf
grep -E "^export" $T/etc/casper.conf
: > $T/etc/fstab
printf "overlay\nsquashfs\nisofs\nloop\nsr_mod\nsd_mod\nahci\nata_piix\n" >> $T/etc/initramfs-tools/modules
chroot $T update-initramfs -u -k all
rm -f $T/etc/resolv.conf; ln -s ../run/systemd/resolve/stub-resolv.conf $T/etc/resolv.conf
mkdir -p image/casper image/isolinux
cp $T/boot/vmlinuz-6.8.0-146-generic image/casper/vmlinuz
cp $T/boot/initrd.img-6.8.0-146-generic image/casper/initrd
chmod 644 image/casper/*
cp /usr/lib/ISOLINUX/isolinux.bin /usr/lib/syslinux/modules/bios/ldlinux.c32 image/isolinux/
cat > image/isolinux/isolinux.cfg <<'C'
DEFAULT live
PROMPT 0
TIMEOUT 1
LABEL live
  KERNEL /casper/vmlinuz
  APPEND initrd=/casper/initrd boot=casper quiet loglevel=0 systemd.show_status=0 nowatchdog username=player hostname=launchos
C
rm -f image/casper/filesystem.squashfs
mksquashfs root image/casper/filesystem.squashfs -comp zstd -Xcompression-level 10 -b 256K -noappend -e root/boot/vmlinuz-6.8.0-146-generic -e root/boot/initrd.img-6.8.0-146-generic
xorriso -as mkisofs -o LaunchOS.iso -isohybrid-mbr /usr/lib/ISOLINUX/isohdpfx.bin -c isolinux/boot.cat -b isolinux/isolinux.bin -no-emul-boot -boot-load-size 4 -boot-info-table -V LAUNCHOS -J -R image
ls -lh LaunchOS.iso
echo MK_DONE
