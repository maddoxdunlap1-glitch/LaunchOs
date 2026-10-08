O=/tmp/claude-0/-home-claude/238c829b-9097-5fd1-973a-842ef65fdfce/scratchpad
cd $O
K(){ timeout 20 python3 mon.py monb "$@"; }
st(){ timeout 40 python3 sh2.py ser.sock "echo STAT web=\$(pgrep -c WebKitWebProces) avail=\$(awk '/MemAvailable/{print int(\$2/1024)}' /proc/meminfo)MB launcher=\$(ps -o rss= -p \$(pgrep -f launch.py) | awk '{print int(\$1/1024)}')MB" | grep -ao "STAT.*MB" | tail -1; }
st
for round in 1 2; do
  for x in 549 670 791 307; do
    timeout 20 python3 qmp.py qmp click $x 500 >/dev/null; sleep 14; K "sendkey meta_l" SLEEP:4
  done
  echo "round $round"; st
done
