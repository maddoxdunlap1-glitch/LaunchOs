#!/bin/bash
# Applies the v0.6 system changes to the OS image.
set -ex
O=/tmp/claude-0/-home-claude/238c829b-9097-5fd1-973a-842ef65fdfce/scratchpad
R=$O/iso/root
cleanup() { for m in dev/pts dev proc sys run; do umount -l $R/$m 2>/dev/null || true; done; }
trap cleanup EXIT
mount --bind /dev $R/dev; mount --bind /dev/pts $R/dev/pts; mount -t proc proc $R/proc; mount -t sysfs sys $R/sys; mount -t tmpfs tmpfs $R/run
mkdir -p $R/run/systemd/resolve; cp /etc/resolv.conf $R/run/systemd/resolve/stub-resolv.conf
APT="chroot $R env DEBIAN_FRONTEND=noninteractive apt-get -y -o Dpkg::Options::=--force-confold"
$APT update -qq
$APT install --no-install-recommends zstd
$APT clean

# files
cp -a $O/sys6/. $R/
rm -f $R/usr/local/sbin/launchos-sober
chmod 755 $R/usr/local/bin/launchos-session $R/usr/local/bin/launchos-inner $R/usr/local/sbin/launchos-*
chmod 644 $R/usr/local/sbin/launchos-status
mkdir -p $R/etc/launchos $R/media/player
chroot $R chown player:player /media/player

# Wi-Fi: iwd connects, networkd gets an address; player may talk to iwd
chroot $R groupadd -f netdev
chroot $R usermod -aG netdev player
chroot $R systemctl enable iwd.service
# PipeWire runs inside the session (no user systemd here): stop its user units from auto-starting twice
chroot $R systemctl --global disable pipewire.socket pipewire-pulse.socket wireplumber.service filter-chain.service 2>/dev/null || true

# Firmware: keep PC graphics, Wi-Fi, Bluetooth, sound and storage; drop server/network-card blobs
cd $R/usr/lib/firmware
rm -rf mellanox mrvl/prestera qcom netronome qed cxgb4 bnx2x bnx2 dpaa2 liquidio cavium qlogic \
       ql2*.bin* ixp4xx inside-secure meson amlogic imx nxp ti-keystone cnm/ mediatek/mt8* \
       intel/ipu intel/vsc intel/avs 2>/dev/null || true
cd /
du -sm $R/usr/lib/firmware

# boot image with the new firmware and zstd compression
chroot $R update-initramfs -u -k all
ls -la $R/boot/initrd.img-*
echo APPLY_DONE
