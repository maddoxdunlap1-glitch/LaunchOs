#!/bin/bash
# The VirtualBox files that go in LaunchOS.zip next to LaunchOS.iso:
#   LaunchOS.vbox          a ready-made machine (Debian 64-bit, 4 GB, 4 CPUs, EFI off)
#   LaunchOS-data.vdi      its save disk: empty, labelled "persistence" for Debian's live system
#   LaunchOS-storage.vdi   a spare empty drive to try Files on
#
#   sudo ./make-vbox.sh OUTDIR
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
OUT=${1:?usage: make-vbox.sh OUTDIR}
mkdir -p "$OUT"
T=$(mktemp -d)
truncate -s 32G "$T/data.img"
mkfs.ext4 -q -F -L persistence -E lazy_itable_init=1,lazy_journal_init=1 "$T/data.img"
mkdir "$T/m"; mount -o loop "$T/data.img" "$T/m"
echo "/ union" > "$T/m/persistence.conf"
umount "$T/m"
rm -f "$OUT/LaunchOS-data.vdi"
qemu-img convert -O vdi "$T/data.img" "$OUT/LaunchOS-data.vdi"
rm -rf "$T"
# the machine file points at the save disk by its id: use the new disk's
uuid=$(python3 - "$OUT/LaunchOS-data.vdi" <<'PY'
import sys, uuid
with open(sys.argv[1], 'rb') as f:
    f.seek(0x188)   # VDI header: the image's own id
    print(uuid.UUID(bytes_le=f.read(16)))
PY
)
python3 - "$HERE/LaunchOS.vbox" "$OUT/LaunchOS.vbox" "$uuid" <<'PY'
import re, sys
src, dst, u = sys.argv[1:]
s = open(src).read()
old = re.search(r'HardDisk uuid="\{([0-9a-f-]+)\}" location="LaunchOS-data.vdi"', s).group(1)
open(dst, 'w').write(s.replace(old, u))
PY
cp "$HERE/LaunchOS-storage.vdi" "$OUT/"
ls -la "$OUT"
