#!/bin/bash
# make-update.sh VERSION OUTDIR [APT PACKAGES...]
# Builds the small LaunchOS update package published with each release:
#   launchos-update.tar.gz  LaunchOS's own files (the launcher pages and its system scripts)
#   launchos-update.json    version, SHA-256 and the Ubuntu packages it needs
set -e
O=/tmp/claude-0/-home-claude/238c829b-9097-5fd1-973a-842ef65fdfce/scratchpad
V=$1; OUT=$2; shift 2
S=$(mktemp -d)
mkdir -p $S/opt/launcher
cp -a $O/ui/. $S/opt/launcher/
cp -a $O/sys6/. $S/
rm -rf $S/opt/launcher/__pycache__ $S/etc/launchos/installed
find $S -name __pycache__ -prune -exec rm -rf {} +
# only LaunchOS's own places go in (the updater refuses anything else anyway)
keep="opt/launcher usr/local/bin usr/local/sbin usr/local/lib/launchos etc/launchos etc/systemd/system etc/udev/rules.d etc/tmpfiles.d"
printf 'NAME="LaunchOS"\nVERSION="%s"\nBUILD_DATE="%s"\n' "$V" "$(date -u +%F)" > $S/etc/launchos-release
rm -f $S/etc/launchos/update.conf   # each PC keeps its own setting
find $S/etc/systemd/system -type f ! -name 'launch*' -delete 2>/dev/null || true
mkdir -p $OUT
( cd $S && tar --owner=0 --group=0 --numeric-owner --sort=name -czf $OUT/launchos-update.tar.gz $keep etc/launchos-release )
sha=$(sha256sum $OUT/launchos-update.tar.gz | cut -d' ' -f1)
python3 - "$V" "$sha" "$OUT" "$@" <<'PY'
import json, sys
v, sha, out, *apt = sys.argv[1:]
notes = open(out + '/notes.txt').read().strip() if __import__('os').path.exists(out + '/notes.txt') else ''
json.dump({'version': v, 'sha256': sha, 'file': 'launchos-update.tar.gz', 'apt': apt, 'full': False, 'notes': notes},
          open(out + '/launchos-update.json', 'w'), indent=1)
PY
rm -rf $S
ls -la $OUT; tar tzf $OUT/launchos-update.tar.gz | head -5; tar tzf $OUT/launchos-update.tar.gz | wc -l
