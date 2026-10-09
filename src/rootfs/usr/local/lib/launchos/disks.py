"""Shared by the LaunchOS drive scripts (run as root): finding drives, telling which
ones LaunchOS itself depends on, mounting them for the player, and reporting progress."""
import fcntl, json, os, re, stat, subprocess, time

MEDIA = "/media/player"
STATUS = "/run/launchos-status"
EJECTED = STATUS + "/ejected"
FS = ("vfat", "exfat", "ntfs", "ext4", "ext3", "ext2", "btrfs", "xfs")
# partitions that belong to an operating system, never shown or opened
SYSTEM_PARTTYPES = {
    "c12a7328-f81f-11d2-ba4b-00a0c93ec93b",  # EFI system
    "de94bba4-06d1-4d40-a16a-bfd50179d6ac",  # Windows recovery
    "e3c9e316-0b5c-4db8-817d-f92df00215ae",  # Microsoft reserved
    "21686148-6449-6e6f-744e-656564454649",  # BIOS boot
    "0xef", "0x27",
}
DISK = re.compile(r"/dev/(sd[a-z]{1,2}|vd[a-z]{1,2}|nvme\d+n\d+|mmcblk\d+)")
PART = re.compile(r"/dev/(sd[a-z]{1,2}\d{1,3}|vd[a-z]{1,2}\d{1,3}|nvme\d+n\d+p\d{1,3}|mmcblk\d+p\d{1,3})")


def sh(*cmd, timeout=120):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as e:
        return subprocess.CompletedProcess(cmd, 1, "", str(e))


def lsblk(dev=None):
    args = ["lsblk", "-J", "-b", "-p", "-o",
            "NAME,TYPE,FSTYPE,LABEL,UUID,RM,TRAN,RO,MOUNTPOINTS,PARTTYPE,SIZE,MODEL,PKNAME"]
    if dev:
        args.append(dev)
    try:
        return json.loads(sh(*args, timeout=10).stdout or "{}").get("blockdevices", [])
    except ValueError:
        return []


def source(target):
    return sh("findmnt", "-no", "SOURCE", target, timeout=10).stdout.strip()


def disk_of(dev):
    pk = sh("lsblk", "-ndpo", "PKNAME", dev, timeout=10).stdout.split()
    return pk[0] if pk else dev


def ancestors(dev):
    """A device and everything under it, down to the physical drive (through partitions,
    device-mapper and loop devices)."""
    return set(sh("lsblk", "-nsrpo", "NAME", dev, timeout=10).stdout.split()) | {dev}


SAVE_LABELS = ("persistence",)   # the save area Debian's live system uses


def system_disks():
    """Drives (and their parts) LaunchOS runs from, keeps its saves on, or is installed on."""
    out = set()
    devs = [source(t) for t in ("/run/live/medium", "/", "/boot/efi", "/var/log", "/home")]
    # the live system's own disks: the LaunchOS stick or disc and the save area
    try:
        with open("/proc/self/mounts") as f:
            devs += [l.split()[0] for l in f if len(l.split()) > 1 and l.split()[1].startswith("/run/live/")]
    except OSError:
        pass
    # every drive labelled for saves (a second stick may carry the same label); lsblk reads the
    # labels the system already knows, without probing every drive again
    for line in sh("lsblk", "-rnpo", "NAME,LABEL", timeout=10).stdout.splitlines():
        p = line.split(" ", 1)
        if len(p) == 2 and p[1] in SAVE_LABELS:
            devs.append(p[0])
    for d in devs:
        if d.startswith("/dev/"):
            out |= ancestors(d)
    return out


def rdev(path):
    try:
        st = os.stat(path)
        return st.st_rdev if stat.S_ISBLK(st.st_mode) else None
    except OSError:
        return None


def in_use(nodes):
    """Mount points of these devices, and whether anything else holds them (swap,
    device-mapper, RAID), compared by device number rather than by name."""
    devs = {rdev(n.get("name", "")) for n in nodes} - {None}
    points = [p for p, (src, _) in mounts().items() if src.startswith("/dev/") and rdev(src) in devs]
    held = False
    for n in nodes:
        name = os.path.basename(n.get("name", ""))
        holders = f"/sys/class/block/{name}/holders"
        if os.path.isdir(holders) and os.listdir(holders):
            held = True
    with open("/proc/swaps") as f:
        for line in f.read().splitlines()[1:]:
            if line.split() and rdev(line.split()[0]) in devs:
                held = True
    return points, held


def mounts():
    """{mount point: (device, options)} from the kernel's list."""
    out = {}
    with open("/proc/self/mounts") as f:
        for line in f:
            p = line.split()
            if len(p) >= 4:
                unesc = lambda s: re.sub(r"\\([0-7]{3})", lambda m: chr(int(m.group(1), 8)), s)
                out[unesc(p[1])] = (unesc(p[0]), p[3])
    return out


def status(job, step, pct, done=False, err="", **extra):
    os.makedirs(STATUS, exist_ok=True)
    os.chmod(STATUS, 0o755)
    path = os.path.join(STATUS, job + ".json")
    with open(path + ".tmp", "w") as f:
        json.dump(dict(extra, step=step, percent=int(pct), done=bool(done), error=err), f)
    os.chmod(path + ".tmp", 0o644)
    os.replace(path + ".tmp", path)


def lock(wait=True):
    """One drive job at a time (mounting, ejecting, formatting, installing). Returns the
    lock's file, or None when not waiting and another job holds it."""
    os.makedirs(STATUS, exist_ok=True)
    fd = os.open(os.path.join(STATUS, ".drives.lock"), os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | (0 if wait else fcntl.LOCK_NB))
    except BlockingIOError:
        os.close(fd)
        return None
    return fd


def prepare_media():
    """/media/player belongs to root, so only root makes and removes the drive folders in it
    (each drive itself is mounted as the player's). Anything else found there is cleared."""
    try:
        st = os.lstat(MEDIA)
        if not stat.S_ISDIR(st.st_mode):
            os.unlink(MEDIA)
            raise FileNotFoundError
    except FileNotFoundError:
        os.makedirs(MEDIA, mode=0o755, exist_ok=True)
        st = os.lstat(MEDIA)
    if st.st_uid != 0 or st.st_gid != 0:
        os.chown(MEDIA, 0, 0, follow_symlinks=False)
    os.chmod(MEDIA, 0o755)
    m = mounts()
    for name in os.listdir(MEDIA):
        d = os.path.join(MEDIA, name)
        if d in m:
            continue
        try:
            st = os.lstat(d)
            if stat.S_ISDIR(st.st_mode):
                os.rmdir(d)
            else:
                os.unlink(d)
        except OSError:
            pass


def ejected():
    try:
        with open(EJECTED) as f:
            return set(f.read().split())
    except OSError:
        return set()


def set_ejected(uuids):
    with open(EJECTED + ".tmp", "w") as f:
        f.write("\n".join(sorted(u for u in uuids if u)) + "\n")
    os.chmod(EJECTED + ".tmp", 0o644)
    os.replace(EJECTED + ".tmp", EJECTED)


def folder_name(label, uuid, dev):
    base = re.sub(r"[^A-Za-z0-9._-]", "_", label or uuid or os.path.basename(dev))[:40].strip("._") or "Drive"
    return base


def mount(dev, fs, label="", uuid=""):
    """Mount a drive at /media/player/<name>, owned by the player. Returns the folder or ''."""
    prepare_media()
    taken = mounts()
    base = folder_name(label, uuid, dev)
    d, n = os.path.join(MEDIA, base), 1
    while d in taken or os.path.lexists(d):
        n += 1
        d = os.path.join(MEDIA, f"{base}_{n}")
    os.mkdir(d, 0o755)
    st = os.lstat(d)   # a fresh, real folder of root's: never mount over anything else
    if not stat.S_ISDIR(st.st_mode) or st.st_uid != 0:
        return ""
    common = "nosuid,nodev"
    if fs == "vfat":
        tries = [["mount", "-t", "vfat", "-o", common + ",uid=1000,gid=1000,umask=022,utf8", dev, d]]
    elif fs == "exfat":
        tries = [["mount", "-t", "exfat", "-o", common + ",uid=1000,gid=1000,umask=022", dev, d]]
    elif fs == "ntfs":
        o = common + ",uid=1000,gid=1000,umask=022,windows_names"
        # a Windows drive that was hibernated or not shut down cleanly opens read-only
        tries = [["mount", "-t", "ntfs-3g", "-o", o, dev, d], ["mount", "-t", "ntfs-3g", "-o", o + ",ro", dev, d]]
    else:
        tries = [["mount", "-o", common, dev, d]]
    for cmd in tries:
        if sh(*cmd, timeout=60).returncode == 0:
            return d
    try:
        os.rmdir(d)
    except OSError:
        pass
    return ""


def cleanup():
    """Let go of folders whose drive was unplugged."""
    prepare_media()
    m = mounts()
    for name in os.listdir(MEDIA):
        d = os.path.join(MEDIA, name)
        if d in m:
            dev = m[d][0]
            if dev.startswith("/dev/") and not os.path.exists(dev):
                sh("umount", "-l", d, timeout=20)
                m = mounts()
        if d not in m and os.path.isdir(d) and not os.path.islink(d):
            try:
                os.rmdir(d)
            except OSError:
                pass


def usable(node, sysdisks):
    """Can this partition (or whole-drive file system) be opened?"""
    return (node.get("fstype") in FS and node.get("name") not in sysdisks
            and (node.get("parttype") or "").lower() not in SYSTEM_PARTTYPES
            and node.get("label") not in SAVE_LABELS)


def wait_for(path, seconds=10):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if os.path.exists(path):
            return True
        time.sleep(0.25)
    return os.path.exists(path)
