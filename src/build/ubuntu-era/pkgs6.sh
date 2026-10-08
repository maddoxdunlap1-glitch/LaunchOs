#!/bin/bash
# v0.6 packages: Steam, Wine, Vulkan/32-bit, PipeWire, iwd, Flatpak, installer tools, filesystems, firmware.
set -ex
O=/tmp/claude-0/-home-claude/238c829b-9097-5fd1-973a-842ef65fdfce/scratchpad
R=$O/iso/root
P=http://127.0.0.1:34563
cleanup() { for m in dev/pts dev proc sys run; do umount -l $R/$m 2>/dev/null || true; done; }
trap cleanup EXIT
mount --bind /dev $R/dev; mount --bind /dev/pts $R/dev/pts; mount -t proc proc $R/proc; mount -t sysfs sys $R/sys; mount -t tmpfs tmpfs $R/run
mkdir -p $R/run/systemd/resolve; cp /etc/resolv.conf $R/run/systemd/resolve/stub-resolv.conf
cat > $R/etc/apt/sources.list <<EOF
deb http://archive.ubuntu.com/ubuntu noble main restricted universe multiverse
deb http://archive.ubuntu.com/ubuntu noble-updates main restricted universe multiverse
deb http://security.ubuntu.com/ubuntu noble-security main restricted universe multiverse
EOF
APT="chroot $R env DEBIAN_FRONTEND=noninteractive apt-get -y -o Dpkg::Options::=--force-confold"
chroot $R dpkg --add-architecture i386
$APT update
# Steam's installer asks to accept its license through debconf
echo 'steam steam/question select I AGREE' | chroot $R debconf-set-selections
echo 'steam steam/license note ' | chroot $R debconf-set-selections
$APT install --no-install-recommends \
  steam-installer steam-libs-amd64 steam-libs-i386 zenity xdg-utils \
  wine wine64 wine32:i386 \
  mesa-vulkan-drivers mesa-vulkan-drivers:i386 libvulkan1 libvulkan1:i386 libgl1-mesa-dri:i386 libgl1:i386 vulkan-tools mesa-utils \
  pipewire pipewire-pulse pipewire-alsa wireplumber pulseaudio-utils \
  iwd wireless-regdb \
  flatpak \
  parted gdisk dosfstools e2fsprogs rsync grub2-common grub-pc-bin grub-efi-amd64-bin efibootmgr \
  ntfs-3g exfatprogs \
  linux-firmware amd64-microcode intel-microcode
$APT clean
chroot $R dpkg -l | awk '/^ii/{n++} END{print n" packages"}'
du -sm $R/usr/lib/firmware $R/lib/firmware 2>/dev/null || true
echo PKGS_DONE
