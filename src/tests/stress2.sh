O=/tmp/claude-0/-home-claude/238c829b-9097-5fd1-973a-842ef65fdfce/scratchpad
cd $O
K(){ timeout 20 python3 mon.py monb "$@"; }
st(){ timeout 40 python3 sh2.py ser.sock "echo; echo; echo; st" | grep -a "^STAT"; }
for round in 1 2 3; do
  for x in 549 670 791 307; do
    timeout 20 python3 qmp.py qmp click $x 500 >/dev/null; sleep 12; K "sendkey meta_l" SLEEP:4
  done
done
echo "after 12 opens:"; st
# end every running app: Ctrl+click its tile, then End task
for x in 549 670 791 307; do
  timeout 20 python3 qmp.py qmp click $x 500 ctrl >/dev/null; sleep 3
  K "sendkey down" SLEEP:0.4 "sendkey down" SLEEP:0.6 "sendkey ret" SLEEP:3
done
sleep 5; echo "after End task on all:"; st
