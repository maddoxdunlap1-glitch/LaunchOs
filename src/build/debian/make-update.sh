#!/bin/bash
# Builds the small LaunchOS update package published with each release
# (Settings > Updates downloads it):
#   launchos-update.tar.gz  LaunchOS's own files (the launcher and its system scripts)
#   launchos-update.json    version, SHA-256, the Debian packages it needs, and "full"
#
#   ./make-update.sh VERSION OUTDIR [APT PACKAGES...]
#   FULL=1 ./make-update.sh ...   a release that can't be reached by updating (a new base
#                                 system): older versions are told to download it fresh
set -e
HERE=$(cd "$(dirname "$0")" && pwd)
SRC=$(cd "$HERE/../.." && pwd)
V=${1:?usage: make-update.sh VERSION OUTDIR [APT PACKAGES...]}; OUT=$2; shift 2
S=$(mktemp -d)
mkdir -p "$S/opt/launcher"
cp -a "$SRC/ui/." "$S/opt/launcher/"
cp -a "$SRC/rootfs/." "$S/"
rm -rf "$S/etc/launchos/installed"
find "$S" -name __pycache__ -prune -exec rm -rf {} +
# only LaunchOS's own places go in (the updater refuses anything else anyway)
keep="opt/launcher usr/local/bin usr/local/sbin usr/local/lib/launchos etc/launchos etc/systemd/system etc/udev/rules.d etc/tmpfiles.d"
printf 'NAME="LaunchOS"\nVERSION="%s"\nBUILD_DATE="%s"\n' "$V" "$(date -u +%F)" > "$S/etc/launchos-release"
rm -f "$S/etc/launchos/update.conf"   # each PC keeps its own setting
find "$S/etc/systemd/system" -type f ! -name 'launch*' -delete 2>/dev/null || true
mkdir -p "$OUT"
( cd "$S" && tar --owner=0 --group=0 --numeric-owner --sort=name -czf "$OUT/launchos-update.tar.gz" $keep etc/launchos-release )
sha=$(sha256sum "$OUT/launchos-update.tar.gz" | cut -d' ' -f1)
python3 - "$V" "$sha" "$OUT" "${FULL:-0}" "$@" <<'PY'
import json, os, sys
v, sha, out, full, *apt = sys.argv[1:]
notes = open(out + '/notes.txt').read().strip() if os.path.exists(out + '/notes.txt') else ''
json.dump({'version': v, 'sha256': sha, 'file': 'launchos-update.tar.gz', 'apt': apt, 'full': full == '1', 'notes': notes},
          open(out + '/launchos-update.json', 'w'), indent=1)
PY
rm -rf "$S"
cat "$OUT/launchos-update.json"; echo; tar tzf "$OUT/launchos-update.tar.gz" | wc -l
