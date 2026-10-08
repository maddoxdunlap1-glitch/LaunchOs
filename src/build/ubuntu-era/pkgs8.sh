#!/bin/bash
set -ex
O=/tmp/claude-0/-home-claude/238c829b-9097-5fd1-973a-842ef65fdfce/scratchpad
R=$O/iso/root
cleanup() { for m in dev/pts dev proc sys run; do umount -l $R/$m 2>/dev/null || true; done; }
trap cleanup EXIT
mount --bind /dev $R/dev; mount --bind /dev/pts $R/dev/pts; mount -t proc proc $R/proc; mount -t sysfs sys $R/sys; mount -t tmpfs tmpfs $R/run
mkdir -p $R/run/systemd/resolve; cp /etc/resolv.conf $R/run/systemd/resolve/stub-resolv.conf
APT="chroot $R env DEBIAN_FRONTEND=noninteractive apt-get -y -o Dpkg::Options::=--force-confold"
$APT update -qq
$APT install --no-install-recommends gir1.2-vte-3.91 fonts-dejavu-core
chroot $R python3 -c "import gi; gi.require_version('Vte','3.91'); from gi.repository import Vte; print('VTE', Vte.get_major_version(), Vte.get_minor_version())"
$APT clean
rm -rf $R/var/lib/apt/lists/*
