#!/bin/bash
# Builds the Debian 13 base system for LaunchOS: Debian plus every package LaunchOS needs,
# the player account and Flathub's app catalog (with icons). LaunchOS's own files are added
# afterwards by make-image.sh, so the base only needs rebuilding when packages change.
#
#   sudo ./base.sh WORKDIR       ->  WORKDIR/base.squashfs, WORKDIR/packages.lst
#
# Needs: debootstrap, squashfs-tools, a network connection. Runs on GitHub Actions.
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
W=${1:?usage: base.sh WORKDIR}
R=$W/root
MIRROR=http://deb.debian.org/debian
mkdir -p "$W"
rm -rf "$R"

debootstrap --arch=amd64 --variant=minbase --components=main,contrib,non-free,non-free-firmware \
  trixie "$R" "$MIRROR"

cat > "$R/etc/apt/sources.list.d/debian.sources" <<EOF
Types: deb
URIs: $MIRROR
Suites: trixie trixie-updates
Components: main contrib non-free non-free-firmware
Signed-By: /usr/share/keyrings/debian-archive-keyring.gpg

Types: deb
URIs: http://security.debian.org/debian-security
Suites: trixie-security
Components: main contrib non-free non-free-firmware
Signed-By: /usr/share/keyrings/debian-archive-keyring.gpg
EOF
rm -f "$R/etc/apt/sources.list"
# no recommended extras: everything LaunchOS needs is listed in packages.txt
printf 'APT::Install-Recommends "false";\nAPT::Install-Suggests "false";\n' > "$R/etc/apt/apt.conf.d/90launchos"
echo launchos > "$R/etc/hostname"
printf '127.0.0.1\tlocalhost\n127.0.1.1\tlaunchos\n::1\tlocalhost ip6-localhost ip6-loopback\n' > "$R/etc/hosts"
echo 'LANG=C.UTF-8' > "$R/etc/default/locale"

cleanup() { for m in dev/pts dev proc sys run; do umount -l "$R/$m" 2>/dev/null || true; done; }
trap cleanup EXIT
mount --bind /dev "$R/dev"; mount --bind /dev/pts "$R/dev/pts"
mount -t proc proc "$R/proc"; mount -t sysfs sys "$R/sys"; mount -t tmpfs tmpfs "$R/run"
cp /etc/resolv.conf "$R/etc/resolv.conf"
IN="chroot $R env DEBIAN_FRONTEND=noninteractive LANG=C.UTF-8"
APT="$IN apt-get -y -o Dpkg::Options::=--force-confold"

$IN dpkg --add-architecture i386
$APT update
# Steam's installer asks to accept Valve's license through debconf
for owner in steam steam-installer; do
  echo "$owner steam/question select I AGREE" | $IN debconf-set-selections
  echo "$owner steam/license note " | $IN debconf-set-selections
done

required=$(sed -n '/^\[optional\]/q;s/#.*//;/\S/p' "$HERE/packages.txt" | tr -s ' \n' ' ')
optional=$(sed -n '/^\[optional\]/,${/^\[/d;s/#.*//;/\S/p}' "$HERE/packages.txt")
$APT install $required
for p in $optional; do
  $APT install "$p" >/dev/null 2>&1 && echo "optional: $p installed" || echo "optional: $p not available"
done

# Flathub, and its app catalog with icons, so the Store and Setup work straight away
$IN flatpak remote-add --system --if-not-exists flathub https://dl.flathub.org/repo/flathub.flatpakrepo
$IN flatpak update --system --appstream -y flathub
ls "$R/var/lib/flatpak/appstream/flathub/x86_64/active/"

# systemd-resolved last: installing it replaces resolv.conf, which the steps above need
$APT install systemd-resolved

# the player account (LaunchOS signs in as player; no password until one is set in Settings)
$IN groupadd -f netdev
$IN useradd -m -u 1000 -s /bin/bash -G audio,video,input,render,netdev player
$IN usermod -p '!' player
$IN passwd -l root

# smaller image: keep the license (copyright) files, drop other docs, manuals and other languages
find "$R/usr/share/doc" -type f ! -name copyright -delete 2>/dev/null || true
find "$R/usr/share/doc" -type d -empty -delete 2>/dev/null || true
rm -rf "$R/usr/share/man" "$R/usr/share/info"
find "$R/usr/share/locale" -mindepth 1 -maxdepth 1 ! -name 'en*' ! -name 'locale.alias' -exec rm -rf {} +
# firmware for server and network-appliance hardware isn't needed on a gaming PC
( cd "$R/usr/lib/firmware" && rm -rf mellanox mrvl/prestera qcom netronome qed cxgb4 bnx2x bnx2 dpaa2 liquidio \
    cavium qlogic ql2*.bin* ixp4xx inside-secure meson amlogic imx nxp ti-keystone intel/ipu intel/vsc 2>/dev/null || true )
$APT clean
rm -rf "$R/var/lib/apt/lists/"* "$R/var/cache/apt/"*.bin "$R/var/log/"*.log "$R/var/log/apt" "$R/tmp/"* "$R/var/tmp/"*

$IN dpkg-query -W -f '${Package}:${Architecture} ${Version}\n' > "$W/packages.lst"
wc -l "$W/packages.lst"
cleanup
trap - EXIT
rm -f "$R/etc/resolv.conf"; ln -s ../run/systemd/resolve/stub-resolv.conf "$R/etc/resolv.conf"
du -sh "$R"

rm -f "$W/base.squashfs"
mksquashfs "$R" "$W/base.squashfs" -comp zstd -Xcompression-level 19 -b 1M -noappend -no-progress
ls -l "$W/base.squashfs"
