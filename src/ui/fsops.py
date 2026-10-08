"""LaunchOS Files: the file operations behind the Files page.

Imported by the launcher for quick things (listing a folder, renaming), and run as its own
process for copying, moving and deleting, so a long copy never slows down or freezes Home:
    python3 fsops.py      reads {"op", "paths", "dest"} as JSON, prints progress as JSON lines.
Everything here stays inside your home folder (not its hidden system folders) and the drives
opened at /media/player.
"""
import errno
import json
import os
import re
import shutil
import signal
import stat
import sys
import threading
import time

HOME = os.path.expanduser('~')


def read(path, default=''):
    try:
        with open(path) as f:
            return f.read()
    except OSError:
        return default


MEDIA = os.environ.get('LAUNCHOS_MEDIA', '/media/player')   # (tests point this elsewhere)
PLACES = ('Downloads', 'Documents', 'Pictures', 'Videos', 'Music')
KINDS = {
    'image': ('.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp', '.svg', '.avif', '.ico', '.jfif'),
    'video': ('.mp4', '.mkv', '.webm', '.mov', '.avi', '.m4v', '.ogv', '.wmv', '.flv', '.mpg', '.mpeg', '.ts', '.3gp'),
    'audio': ('.mp3', '.ogg', '.oga', '.opus', '.flac', '.wav', '.m4a', '.aac', '.wma', '.mid'),
    'program': ('.exe', '.msi'),
    'archive': ('.zip', '.7z', '.rar', '.tar', '.gz', '.tgz', '.xz', '.bz2', '.iso', '.img'),
    'text': ('.txt', '.md', '.log', '.json', '.csv', '.ini', '.cfg', '.conf', '.xml', '.yml', '.yaml', '.nfo', '.srt', '.py', '.sh', '.js', '.css'),
    'doc': ('.pdf',),
    'web': ('.html', '.htm'),
}
FAT_LIKE = ('vfat', 'exfat', 'ntfs', 'ntfs3', 'fuseblk', 'msdos')
BAD_FAT = re.compile(r'[<>:"\\|?*\x00-\x1f]')


class FsError(Exception):
    pass


class Cancelled(Exception):
    pass


def file_kind(name):
    low = name.lower()
    for kind, exts in KINDS.items():
        if low.endswith(exts):
            return kind
    return 'other'


def mount_table():
    """{mount point: (device, type, read-only)}"""
    out = {}
    for line in read('/proc/self/mounts').splitlines():
        p = line.split()
        if len(p) >= 4:
            unesc = lambda s: re.sub(r'\\([0-7]{3})', lambda m: chr(int(m.group(1), 8)), s)
            out[unesc(p[1])] = (unesc(p[0]), p[2], 'ro' in p[3].split(','))
    return out


def mount_of(path, table=None):
    """(mount point, device, type, read-only) of the file system a path is on."""
    table = table or mount_table()
    best = '/'
    for mnt in table:
        if (path == mnt or path.startswith(mnt.rstrip('/') + '/')) and len(mnt) > len(best):
            best = mnt
    dev, typ, ro = table.get(best, ('', '', False))
    return best, dev, typ, ro


def human(n):
    n = float(n or 0)
    for unit in ('bytes', 'KB', 'MB', 'GB', 'TB'):
        if n < 1024 or unit == 'TB':
            return (f'{int(n)} {unit}' if unit == 'bytes' else f'{n:.1f} {unit}'.replace('.0 ', ' '))
        n /= 1024


def fs_real(path, write=False):
    """The real path if it's in your folders or on an open drive. Raises FsError otherwise."""
    try:
        real = os.path.realpath(str(path))
        plain = os.path.normpath(os.path.join(HOME, str(path)))
    except (TypeError, ValueError):
        raise FsError('That isn’t a valid place.')
    if real != plain:   # Files never follows links: deleting a link must never delete what it points to
        raise FsError('That’s a link to somewhere else, which Files doesn’t open.')
    for root in (HOME, MEDIA):
        if real != root and not real.startswith(root + '/'):
            continue
        parts = [p for p in real[len(root):].split('/') if p]
        if any(p.startswith('.') for p in parts):
            raise FsError('That’s a hidden system folder.')
        if root == MEDIA and parts:
            drive = os.path.join(MEDIA, parts[0])
            if drive not in mount_table():
                raise FsError('That drive isn’t open any more. It may have been unplugged.')
        if write and real in (HOME, MEDIA):
            raise FsError('Files can’t go there. Pick a folder or a drive.')
        return real
    raise FsError('Files only opens your folders and drives.')


def protected(real):
    """Folders that can't be deleted, moved or renamed."""
    if real in (HOME, MEDIA) or os.path.dirname(real) == MEDIA:
        return True
    return os.path.dirname(real) == HOME and os.path.basename(real) in PLACES + ('Desktop',)


def place_name(real):
    """'Downloads', or the drive's name, for messages."""
    if real.startswith(MEDIA + '/'):
        return real[len(MEDIA) + 1:].split('/')[0].replace('_', ' ')
    rel = real[len(HOME) + 1:].split('/')[0] if real.startswith(HOME + '/') else ''
    return rel or 'your folders'


def clean_name(name, fat):
    """A name the destination drive can store (Windows-style drives refuse some characters)."""
    if not fat:
        return name
    name = BAD_FAT.sub('_', name).rstrip(' .')
    return name or '_'


def check_name(name, folder):
    name = str(name or '').strip()
    if not name or name in ('.', '..'):
        raise FsError('Type a name first.')
    if '/' in name or '\0' in name:
        raise FsError('Names can’t contain a slash (/).')
    if name.startswith('.'):
        raise FsError('Names can’t start with a dot. That would hide it.')
    if len(name.encode('utf-8', 'surrogateescape')) > 255:
        raise FsError('That name is too long.')
    if mount_of(folder)[2] in FAT_LIKE and (BAD_FAT.search(name) or name.endswith(('.', ' '))):
        raise FsError('This drive can’t store these in names:  < > : " \\ | ? *')
    return name


def unique_name(folder, name):
    if not os.path.lexists(os.path.join(folder, name)):
        return name
    stem, ext = os.path.splitext(name)
    if not stem:
        stem, ext = name, ''
    for n in range(2, 10000):
        cand = f'{stem} ({n}){ext}'
        if not os.path.lexists(os.path.join(folder, cand)):
            return cand
    raise FsError('There are too many copies with that name here.')


def fs_message(e):
    """A plain-language reason for a failed file operation."""
    if isinstance(e, FsError):
        return str(e)
    n = getattr(e, 'errno', None)
    msgs = {
        errno.ENOSPC: 'The drive is full.', errno.EDQUOT: 'The drive is full.',
        errno.EIO: 'The drive stopped responding. It may have been unplugged.',
        errno.ENODEV: 'The drive was unplugged.', errno.ENXIO: 'The drive was unplugged.',
        errno.ENOTCONN: 'The drive was unplugged.',
        errno.EROFS: 'This drive is read-only. It may be locked, or Windows may need to check it first.',
        errno.EACCES: 'LaunchOS isn’t allowed to change that.', errno.EPERM: 'LaunchOS isn’t allowed to change that.',
        errno.EFBIG: 'A file is over 4 GB, too big for a FAT32 drive. Format the drive as exFAT to fit it.',
        errno.ENAMETOOLONG: 'A name is too long for that drive.',
        errno.EEXIST: 'There’s already something with that name here.',
        errno.ENOTEMPTY: 'That folder isn’t empty.',
        errno.ENOENT: 'It isn’t there any more. It may have been moved, or the drive unplugged.',
        errno.EINVAL: 'A name has characters that drive can’t store.',
        errno.EILSEQ: 'A name has characters that drive can’t store.',
        errno.ELOOP: 'That folder links back to itself.',
    }
    return msgs.get(n, 'Something went wrong' + (f' ({os.strerror(n)}).' if n else '.'))


def fs_list(path, busy=False):
    try:
        real = fs_real(path)
        if not os.path.isdir(real):
            raise FsError('That folder isn’t there any more.')
        entries = []
        with os.scandir(real) as it:
            for e in it:
                if e.name.startswith('.launchos-copy-') and not busy:
                    FsJob.discard(None, e.path)   # half a copy, left when a drive was pulled out mid-copy
                    continue
                if e.name.startswith('.') or (real == HOME and e.name == 'snap'):
                    continue
                try:
                    if e.is_symlink():   # links aren't shown: Files only handles real files and folders
                        continue
                    st = e.stat(follow_symlinks=False)
                    isdir = e.is_dir(follow_symlinks=False)
                except OSError:
                    continue
                entries.append({'name': e.name, 'dir': isdir, 'size': None if isdir else st.st_size,
                                'mtime': int(st.st_mtime), 'kind': 'folder' if isdir else file_kind(e.name)})
                if len(entries) >= 5000:
                    break
        entries.sort(key=lambda x: (not x['dir'], x['name'].casefold()))
        st = os.statvfs(real)
        mnt, dev, typ, ro = mount_of(real)
        return {'path': real, 'entries': entries, 'truncated': len(entries) >= 5000,
                'free': st.f_bavail * st.f_frsize, 'total': st.f_blocks * st.f_frsize,
                'writable': real not in (HOME, MEDIA) and not ro and os.access(real, os.W_OK),
                'readonly': ro, 'fat': typ in FAT_LIKE, 'place': place_name(real)}
    except (OSError, FsError) as e:
        return {'error': fs_message(e)}


def fs_mkdir(arg):
    arg = arg if isinstance(arg, dict) else {}
    try:
        folder = fs_real(arg.get('path'), write=True)
        name = unique_name(folder, check_name(arg.get('name') or 'New folder', folder))
        os.mkdir(os.path.join(folder, name))
        return {'ok': True, 'name': name}
    except (OSError, FsError) as e:
        return {'ok': False, 'error': fs_message(e)}


def fs_rename(arg):
    arg = arg if isinstance(arg, dict) else {}
    try:
        real = fs_real(arg.get('path'))
        if protected(real):
            raise FsError('That folder can’t be renamed.')
        folder = os.path.dirname(real)
        fs_real(folder, write=True)
        name = check_name(arg.get('name'), folder)
        if name == os.path.basename(real):
            return {'ok': True, 'name': name}
        target = os.path.join(folder, name)
        # on drives that ignore upper/lower case, "photo" -> "Photo" is the same file
        if os.path.lexists(target) and not os.path.samefile(target, real):
            raise FsError('There’s already something called ' + name + ' here.')
        os.rename(real, target)
        return {'ok': True, 'name': name}
    except (OSError, FsError) as e:
        return {'ok': False, 'error': fs_message(e)}


class FsJob:
    """Copies, moves or deletes in the background. One at a time; Files shows its progress.

    Copies go to a hidden temporary name first and get their real name only when complete,
    so a stopped or failed copy never leaves a half-finished file or folder that looks whole.
    A move deletes its source only after the copy is safely written to the drive."""

    def __init__(self, op, paths, dest=None):
        self.op, self.paths, self.dest = op, paths, dest
        self.cancel = False
        self.state = {'op': op, 'step': 'Getting ready', 'bytes': 0, 'total_bytes': 0, 'files': 0, 'total_files': 0,
                      'current': '', 'done': False, 'error': '', 'result': '', 'dest': '', 'speed': 0, 'stopped': False,
                      'items': 0, 'total_items': len(paths), 'skipped': 0}
        self.t0 = time.monotonic()

    def info(self):
        s = dict(self.state)
        dt = time.monotonic() - self.t0
        s['speed'] = int(s['bytes'] / dt) if dt > 1 else 0
        return s

    def run(self):
        try:
            if self.op == 'delete':
                self.delete()
            else:
                self.paste()
        except Cancelled:
            self.state.update(stopped=True, result=self.stopped_text())
        except (OSError, FsError) as e:
            self.state['error'] = fs_message(e)
            if self.state['items']:
                self.state['error'] += ' ' + self.done_text()
        except Exception as e:   # never leave Files waiting on a job that died
            self.state['error'] = 'Something went wrong: ' + str(e)
        self.state['done'] = True

    def done_text(self):
        n, verb = self.state['items'], {'copy': 'copied', 'move': 'moved', 'delete': 'deleted'}[self.op]
        return f'{n} of {self.state["total_items"]} item{"" if self.state["total_items"] == 1 else "s"} {"was" if n == 1 else "were"} {verb} before that.'

    def stopped_text(self):
        if not self.state['items']:
            return 'Stopped. Nothing was ' + {'copy': 'copied.', 'move': 'moved.', 'delete': 'deleted.'}[self.op]
        return 'Stopped. ' + self.done_text()

    # ---- copy and move ----
    def scan(self, real):
        """(bytes, files, biggest file) in a file or folder. Only regular files count:
        links, devices and pipes are never copied."""
        st = os.lstat(real)
        if stat.S_ISREG(st.st_mode):
            return st.st_size, 1, st.st_size
        if not stat.S_ISDIR(st.st_mode):
            return 0, 0, 0
        b = n = big = 0
        for dirpath, dirs, files in os.walk(real):
            for f in files:
                try:
                    s = os.lstat(os.path.join(dirpath, f))
                except OSError:
                    continue
                if stat.S_ISREG(s.st_mode):
                    b += s.st_size; n += 1; big = max(big, s.st_size)
        return b, n, big

    def paste(self):
        move = self.op == 'move'
        dest = fs_real(self.dest, write=True)
        if not os.path.isdir(dest):
            raise FsError('That folder isn’t there any more.')
        mnt, _, typ, ro = mount_of(dest)
        if ro or not os.access(dest, os.W_OK):
            raise FsError('This drive is read-only. It may be locked, or Windows may need to check it first.')
        fat = typ in FAT_LIKE
        self.state['dest'] = place_name(dest)
        plan, need, total_files, biggest = [], 0, 0, (0, '')
        for p in self.paths:
            src = fs_real(p)
            name = os.path.basename(src)
            mode = os.lstat(src).st_mode
            if not (stat.S_ISDIR(mode) or stat.S_ISREG(mode)):
                raise FsError(name + ' isn’t a normal file, so it can’t be copied.')
            if move and protected(src):
                raise FsError(name + ' can’t be moved.')
            if stat.S_ISDIR(mode) and (dest == src or dest.startswith(src + '/')):
                raise FsError('A folder can’t go inside itself.')
            if move and os.path.dirname(src) == dest:
                continue   # already here
            if move and (mount_of(src)[3] or not os.access(os.path.dirname(src), os.W_OK)):
                raise FsError(name + ' is on a read-only drive, so it can only be copied.')
            b, n, big = self.scan(src)
            same_fs = move and os.stat(src).st_dev == os.stat(dest).st_dev
            if not same_fs:
                need += b
            total_files += n
            if big > biggest[0]:
                biggest = (big, name)
            plan.append((src, same_fs, n))
        if not plan:
            self.state['result'] = 'Nothing to move. It’s already here.'
            return
        st = os.statvfs(dest)
        free = st.f_bavail * st.f_frsize
        if need > free:
            raise FsError(f'Not enough space on {place_name(dest)}: this needs {human(need)} and {human(free)} is free.')
        if typ in ('vfat', 'msdos') and biggest[0] >= 4 << 30:
            raise FsError(f'{biggest[1]} has a file over 4 GB, too big for this drive (FAT32). '
                          'Format the drive as exFAT to fit it, or copy smaller files.')
        self.state.update(total_bytes=need, total_files=total_files, total_items=len(plan),
                          step=('Moving' if move else 'Copying') + ' to ' + place_name(dest))
        external = dest.startswith(MEDIA + '/')
        for src, same_fs, nfiles in plan:
            name = clean_name(os.path.basename(src), fat)
            if same_fs:
                try:
                    os.rename(src, os.path.join(dest, unique_name(dest, name)))
                    self.state['files'] += nfiles
                    self.state['items'] += 1
                    continue
                except OSError as e:
                    if e.errno != errno.EXDEV:   # some folders of the live system can't simply be renamed
                        raise
            self.copy_item(src, dest, name, fat, durable=external or move, move=move)
            if move:
                self.state.update(step='Removing the originals', current=os.path.basename(src))
                self.remove_copied(src)
            self.state['items'] += 1
            if move:
                self.state['step'] = 'Moving to ' + place_name(dest)
        if external and not move:
            self.state.update(step='Finishing writing to the drive', current='')
            os.sync()
        n = len(plan)
        what = os.path.basename(plan[0][0]) if n == 1 else f'{n} items'
        self.state['result'] = f'{"Moved" if move else "Copied"} {what} to {place_name(dest)}.'
        if self.state['skipped']:
            k = self.state['skipped']
            self.state['result'] += f' {k} link{"" if k == 1 else "s"} or special file{"" if k == 1 else "s"} {"was" if k == 1 else "were"} left out.'

    def copy_item(self, src, dest, name, fat, durable, move):
        """Copy one file or folder under a hidden name, then give it its real name."""
        tmp = os.path.join(dest, '.launchos-copy-' + str(os.getpid()) + '-' + str(int(time.time() * 1000) % 10 ** 9))
        try:
            if stat.S_ISDIR(os.lstat(src).st_mode):
                self.copy_tree(src, tmp, fat, durable)
            else:
                self.copy_file(src, tmp, durable)
            target = os.path.join(dest, unique_name(dest, name))
            os.rename(tmp, target)
            if move:
                os.sync()   # everything copied is really on the drive before any original is removed
        except BaseException:
            self.discard(tmp)
            raise

    def discard(self, path):
        try:
            if os.path.isdir(path) and not os.path.islink(path):
                shutil.rmtree(path, ignore_errors=True)
            elif os.path.lexists(path):
                os.unlink(path)
        except OSError:
            pass

    def copy_file(self, src, dst, durable):
        self.state['current'] = os.path.basename(src)
        # never follow a link or wait on a pipe: only regular files are read
        sfd = os.open(src, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            st = os.fstat(sfd)
            if not stat.S_ISREG(st.st_mode):
                self.state['skipped'] += 1
                return
            os.set_blocking(sfd, True)
            fd = os.open(dst, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644)
            with os.fdopen(fd, 'wb') as fo:
                written = 0
                while True:
                    if self.cancel:
                        raise Cancelled()
                    buf = os.read(sfd, 1 << 20)
                    if not buf:
                        break
                    fo.write(buf)
                    self.state['bytes'] += len(buf)
                    written += len(buf)
                    if durable and written % (64 << 20) < len(buf):
                        # USB drives: write out as we go, so progress is real and memory doesn't fill up
                        fo.flush()
                        os.fdatasync(fo.fileno())
                fo.flush()
        finally:
            os.close(sfd)
        try:
            os.utime(dst, (st.st_atime, st.st_mtime))
        except OSError:
            pass
        self.state['files'] += 1

    def copy_tree(self, src, dst, fat, durable):
        os.mkdir(dst)
        with os.scandir(src) as it:
            items = sorted(it, key=lambda e: e.name)
        for e in items:
            if self.cancel:
                raise Cancelled()
            if e.is_dir(follow_symlinks=False):
                self.copy_tree(e.path, os.path.join(dst, unique_name(dst, clean_name(e.name, fat))), fat, durable)
            elif e.is_file(follow_symlinks=False):
                self.copy_file(e.path, os.path.join(dst, unique_name(dst, clean_name(e.name, fat))), durable)
            else:
                self.state['skipped'] += 1

    def remove_copied(self, real):
        """After a move: remove the originals that were copied. Links and special files,
        which weren't copied, stay where they were (and so do their folders)."""
        st = os.lstat(real)
        if not stat.S_ISDIR(st.st_mode):
            if stat.S_ISREG(st.st_mode):
                os.unlink(real)
            return
        for dirpath, dirs, files in os.walk(real, topdown=False):
            for f in files:
                p = os.path.join(dirpath, f)
                if stat.S_ISREG(os.lstat(p).st_mode):
                    os.unlink(p)
            try:
                os.rmdir(dirpath)
            except OSError as e:
                if e.errno not in (errno.ENOTEMPTY, errno.EEXIST):
                    raise

    # ---- delete ----
    def remove(self, real):
        st = os.lstat(real)
        if stat.S_ISDIR(st.st_mode):
            for dirpath, dirs, files in os.walk(real, topdown=False):
                for f in files:
                    if self.cancel:
                        raise Cancelled()
                    os.unlink(os.path.join(dirpath, f))
                    self.state['files'] += 1
                    self.state['current'] = f
                for d in dirs:
                    p = os.path.join(dirpath, d)
                    os.unlink(p) if os.path.islink(p) else os.rmdir(p)
            os.rmdir(real)
        else:
            os.unlink(real)
            self.state['files'] += 1

    def delete(self):
        reals = []
        for p in self.paths:
            real = fs_real(p)
            if protected(real):
                raise FsError(os.path.basename(real) + ' can’t be deleted.')
            reals.append(real)
        self.state.update(total_files=sum(self.scan(r)[1] for r in reals), total_items=len(reals), step='Deleting')
        for real in reals:
            self.remove(real)
            self.state['items'] += 1
        if any(r.startswith(MEDIA + '/') for r in reals):
            os.sync()
        n = len(reals)
        self.state['result'] = 'Deleted ' + (os.path.basename(reals[0]) if n == 1 else f'{n} items') + '.'



def main():
    """Run one copy, move or delete, printing its progress for the launcher."""
    req = json.loads(sys.stdin.readline() or '{}')
    job = FsJob(str(req.get('op')), [str(p) for p in req.get('paths') or []], req.get('dest'))
    signal.signal(signal.SIGTERM, lambda *a: setattr(job, 'cancel', True))   # Stop
    out_lock = threading.Lock()

    def report():
        with out_lock:
            sys.stdout.write(json.dumps(job.info()) + '\n')
            sys.stdout.flush()

    def ticker():
        while not job.state['done']:
            time.sleep(0.25)
            report()
    threading.Thread(target=ticker, daemon=True).start()
    job.run()
    report()


if __name__ == '__main__':
    main()
