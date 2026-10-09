#!/bin/bash
# Builds the small LaunchOS update package published with each release
# (Settings > Updates downloads it):
#   launchos-update.tar.gz    LaunchOS's own files (the launcher and its system scripts)
#   launchos-update-v1.json   for LaunchOS 1.x: version, SHA-256, the Debian packages it needs,
#                             services to switch on, min_version and "full"
#   launchos-update.json      for LaunchOS 0.x, which can't update to 1.x: always "full"
#                             (it tells them to download LaunchOS fresh)
#
#   ./make-update.sh VERSION OUTDIR [APT PACKAGES...]
#   FULL=1         this release can't be reached by updating at all
#   MIN_VERSION=X  the oldest LaunchOS this package can update (default 1.0); older ones are
#                  told to download it fresh
# OUTDIR/notes.txt, if there, is the short note Settings > Updates shows.
set -e
HERE=$(cd "$(dirname "$0")" && pwd)
SRC=$(cd "$HERE/../.." && pwd)
V=${1:?usage: make-update.sh VERSION OUTDIR [APT PACKAGES...]}; OUT=$(realpath -m "${2:?}"); shift 2
S=$(mktemp -d)
mkdir -p "$S/opt/launcher"
cp -a "$SRC/ui/." "$S/opt/launcher/"
cp -a "$SRC/rootfs/." "$S/"
rm -rf "$S/etc/launchos/installed"
find "$S" -name __pycache__ -prune -exec rm -rf {} +
# the root scripts must stay runnable (the updater keeps a file's run permission from the package)
chmod -R go-w "$S"
chmod 755 "$S"/usr/local/sbin/launchos-* "$S"/usr/local/bin/launchos-* "$S/usr/local/lib/launchos/steam-shim/zenity"
chmod 644 "$S/usr/local/sbin/launchos-status"
# only LaunchOS's own places go in (the updater refuses anything else anyway)
keep="opt/launcher usr/local/bin usr/local/sbin usr/local/lib/launchos etc/launchos etc/systemd/system etc/udev/rules.d etc/tmpfiles.d
      etc/sysctl.d/90-launchos.conf etc/systemd/system-preset/00-launchos.preset etc/systemd/zram-generator.conf"
printf 'NAME="LaunchOS"\nVERSION="%s"\nBUILD_DATE="%s"\n' "$V" "$(date -u +%F)" > "$S/etc/launchos-release"
rm -f "$S/etc/launchos/update.conf"   # each PC keeps its own setting
find "$S/etc/systemd/system" -type f ! -name 'launch*' -delete 2>/dev/null || true
mkdir -p "$OUT"
( cd "$S" && tar --owner=0 --group=0 --numeric-owner --sort=name -czf "$OUT/launchos-update.tar.gz" $keep etc/launchos-release )
sha=$(sha256sum "$OUT/launchos-update.tar.gz" | cut -d' ' -f1)
python3 - "$V" "$sha" "$OUT" "${FULL:-0}" "${MIN_VERSION:-1.0}" "$@" <<'PY'
import json, os, sys
v, sha, out, full, minv, *apt = sys.argv[1:]
notes = open(out + '/notes.txt').read().strip() if os.path.exists(out + '/notes.txt') else ''
enable = ['launcher.service', 'launchos-helper.path', 'launchos-reconcile.service', 'launchos-audio.service',
          'launchos-pro-check.timer']
m = {'version': v, 'sha256': sha, 'file': 'launchos-update.tar.gz', 'apt': apt, 'enable': enable,
     'min_version': minv, 'full': full == '1', 'notes': notes}
json.dump(m, open(out + '/launchos-update-v1.json', 'w'), indent=1)
# LaunchOS 0.x: always a fresh download (its system is too different to update in place)
legacy = dict(m, full=True, apt=[], enable=[])
json.dump(legacy, open(out + '/launchos-update.json', 'w'), indent=1)
PY
rm -rf "$S"
cat "$OUT/launchos-update-v1.json"; echo; tar tzvf "$OUT/launchos-update.tar.gz" | grep -E "sbin/launchos-(game|pro|install|status)$"; tar tzf "$OUT/launchos-update.tar.gz" | wc -l
