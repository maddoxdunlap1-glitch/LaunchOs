#!/usr/bin/env python3
"""Start-up test for LaunchOS images (used by the Build workflow, also works on any Linux PC).

Boots a test copy of LaunchOS.iso in QEMU (with KVM when the machine has it, so the timing is close
to a real PC), and measures how long it takes until the sign-in screen is up. Then it takes a
screenshot and collects a start-up report through a root shell on the serial port (only the test
copy has that shell; the real ISO is never changed).

    sudo ci_boot.py WORKDIR OUTDIR [--uefi] [--usb] [--boots N] [--name NAME] [--order]

WORKDIR is make-image.sh's work folder (it holds LaunchOS.iso, image/ and root/).
--usb      write the image to a pretend 8 GB USB stick instead of a disc (the first start sets up
           saving; with --boots 2 the second start is the one that counts)
--order    also list the files read while starting (for boot-order.txt)
"""
import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import tarfile
import time

READY = '/run/player/launchos-ready'


def sh(cmd, **kw):
    return subprocess.run(cmd, shell=True, check=True, **kw)


def make_test_iso(work, out_iso, from_iso=''):
    """A copy of the image whose start-up line also opens a root shell on the serial port."""
    img, root = os.path.join(work, 'image'), os.path.join(work, 'root')
    g = os.path.join(root, 'usr', 'lib', 'grub')
    if from_iso:   # an ISO that was built elsewhere (an older release, say): unpack it
        img = os.path.join(work, 'boottest', 'unpacked')
        shutil.rmtree(img, ignore_errors=True)
        sh(f'xorriso -osirrox on -indev {from_iso} -extract / {img} >/dev/null 2>&1')
        sh(f'chmod -R u+w {img}')
        g = '/usr/lib/grub'
    cfg = os.path.join(img, 'boot', 'grub', 'grub.cfg')
    orig = open(cfg).read()
    test = orig.replace('quiet splash', 'console=ttyS0,115200 console=tty0 systemd.mask=serial-getty@ttyS0.service '
                        'systemd.debug_shell=/dev/ttyS0 quiet splash')
    assert test != orig, 'boot line not found'
    try:
        open(cfg, 'w').write(test)
        sh(f'xorriso -as mkisofs -o {out_iso} -V LAUNCHOS -J -joliet-long -R -l -iso-level 3 '
           f'--grub2-mbr {g}/i386-pc/boot_hybrid.img -partition_offset 16 --mbr-force-bootable '
           f'-append_partition 2 0xef {img}/boot/grub/efiboot.img '
           f'-c boot.catalog -b boot/grub/eltorito.img -no-emul-boot -boot-load-size 4 -boot-info-table --grub2-boot-info '
           f'-eltorito-alt-boot -e boot/grub/efiboot.img -no-emul-boot -boot-load-size full {img} >/dev/null 2>&1')
    finally:
        open(cfg, 'w').write(orig)   # the release image stays exactly as built


class Serial:
    def __init__(self, path, log):
        for _ in range(100):
            if os.path.exists(path):
                break
            time.sleep(0.1)
        self.s = socket.socket(socket.AF_UNIX)
        self.s.connect(path)
        self.s.settimeout(0.2)
        self.log = open(log, 'ab')
        self.n = 0

    def read(self, t):
        out, end = b'', time.monotonic() + t
        while time.monotonic() < end:
            try:
                d = self.s.recv(65536)
            except socket.timeout:
                continue
            if not d:
                break
            out += d
            self.log.write(d)
            self.log.flush()
        return out

    def run(self, cmd, timeout=60):
        """Runs a command in the serial root shell and returns its output (None if no shell yet)."""
        self.n += 1
        mark = f'__E7ND{self.n}__'
        # Ctrl-C and Ctrl-U first: clears anything half-typed (keys sent while the system was still
        # starting can leave the shell waiting for the end of a line). The end mark is printed with
        # $((7)) so the typed command itself never contains it.
        # (bash drops keys typed right after Ctrl-C, so wait a moment, and start with spaces:
        # losing one of those is harmless)
        self.s.send(b'\x03\x15')
        time.sleep(0.3)
        self.read(0.05)
        self.s.send(f'   {cmd}; echo __E$((7))ND{self.n}__\n'.encode())
        out, end = b'', time.monotonic() + timeout
        while time.monotonic() < end:
            out += self.read(0.3)
            if mark.encode() in out:
                text = out.decode(errors='replace').replace('\r', '')
                body = text.split(mark)[0]
                lines = body.split('\n')
                return '\n'.join(lines[1:]).strip()   # (the first line is the echoed command)
        return None


def qemu_args(a, disk, outdisk, work):
    kvm = os.path.exists('/dev/kvm') and os.access('/dev/kvm', os.R_OK | os.W_OK)
    args = ['qemu-system-x86_64', '-m', str(a.mem), '-smp', str(a.cpus), '-display', 'none', '-vga', 'std',
            '-nic', 'user,model=e1000', '-serial', f'unix:{work}/ser.sock,server,nowait',
            '-monitor', f'unix:{work}/mon.sock,server,nowait', '-no-reboot']
    args += ['-enable-kvm', '-cpu', 'host'] if kvm else ['-cpu', 'qemu64,+sse4.1,+sse4.2,+ssse3,+popcnt']
    if a.uefi:
        vars_ = os.path.join(work, 'vars.fd')
        shutil.copy('/usr/share/OVMF/OVMF_VARS_4M.fd', vars_)
        args += ['-M', 'q35', '-drive', 'if=pflash,format=raw,readonly=on,file=/usr/share/OVMF/OVMF_CODE_4M.fd',
                 '-drive', f'if=pflash,format=raw,file={vars_}']
    else:
        args += ['-M', 'pc']
    thr = f',throttling.bps-read={int(a.mbps * 1e6)}' if a.mbps else ''
    if a.usb:
        args += ['-device', 'qemu-xhci,id=xhci', '-drive', f'file={disk},format=raw,if=none,id=stick{thr}',
                 '-device', 'usb-storage,bus=xhci.0,drive=stick,removable=on,bootindex=1']
    else:
        args += ['-drive', f'file={disk},media=cdrom,if=none,id=cd{thr}', '-device', 'ide-cd,drive=cd,bootindex=1']
    # a small blank disk the test writes its report to
    args += ['-drive', f'file={outdisk},format=raw,if=none,id=out', '-device', 'virtio-blk-pci,drive=out,serial=LOSREPORT']
    return args, kvm


def screenshot(work, path):
    try:
        m = socket.socket(socket.AF_UNIX)
        m.connect(os.path.join(work, 'mon.sock'))
        m.settimeout(2)
        ppm = path[:-4] + '.ppm'
        m.send(f'screendump {ppm}\n'.encode())
        time.sleep(1.5)
        m.close()
        from PIL import Image
        Image.open(ppm).save(path)
        os.remove(ppm)
    except Exception as e:
        print('screenshot failed:', e)


REPORT = r'''
mkdir -p /tmp/rep && cd /tmp/rep
cat /proc/cmdline > cmdline.txt
cat /run/player/launchos-ready > ready.txt 2>/dev/null
systemd-analyze > analyze.txt 2>&1
systemd-analyze blame --no-pager > blame.txt 2>&1
systemd-analyze critical-chain launcher.service --no-pager > chain.txt 2>&1
journalctl -b -o short-monotonic --no-pager > journal.txt 2>&1
dmesg > dmesg.txt 2>&1
lsblk -o NAME,SIZE,TYPE,LABEL,FSTYPE,MOUNTPOINTS > lsblk.txt 2>&1
findmnt > findmnt.txt 2>&1
free -m > free.txt; uptime > uptime.txt
ls -la /run/live/ > live.txt 2>&1
cat /home/player/.cache/launchos/ui-errors.log > ui-errors.txt 2>/dev/null
journalctl -b -u launcher --no-pager -o cat > launcher.txt 2>&1
'''
ORDER = r'''
cd /run/live/rootfs/filesystem.squashfs && find . -xdev -type f -size +0 -print0 2>/dev/null | xargs -0 fincore --noheadings --bytes --output RES,FILE 2>/dev/null | awk '$1 > 0 { sub(/^[0-9]+[ \t]+/, ""); print }' > /tmp/rep/bootfiles.txt; wc -l < /tmp/rep/bootfiles.txt
'''


def boot_once(a, disk, work, outdir, label):
    outdisk = os.path.join(work, 'report.img')
    with open(outdisk, 'wb') as f:
        f.truncate(256 * 1024 * 1024)
    for s in ('ser.sock', 'mon.sock'):
        try:
            os.remove(os.path.join(work, s))
        except OSError:
            pass
    args, kvm = qemu_args(a, disk, outdisk, work)
    print(' '.join(args), flush=True)
    t0 = time.monotonic()
    vm = subprocess.Popen(args, stdout=open(os.path.join(outdir, label + '-qemu.log'), 'w'), stderr=subprocess.STDOUT)
    ser = Serial(os.path.join(work, 'ser.sock'), os.path.join(outdir, label + '-serial.log'))
    result = {'label': label, 'kvm': kvm, 'uefi': a.uefi, 'usb': a.usb, 'mbps': a.mbps, 'ready': False}
    ready_wall = None
    limit = a.timeout
    shot_times = [5, 10, 15, 20, 30, 45]
    while time.monotonic() - t0 < limit and vm.poll() is None:
        el = time.monotonic() - t0
        if shot_times and el >= shot_times[0]:
            screenshot(work, os.path.join(outdir, f'{label}-at{shot_times.pop(0):02d}s.png'))
        r = ser.run(f'cat {READY} 2>/dev/null || {{ pgrep -f WebKitWebProcess >/dev/null && echo web; }} || echo no', timeout=1.5)
        last = r.split()[-1] if r else ''
        if last == 'web' and 'web_s' not in result:
            # (older builds don't note when they're ready: the page engine starting is the next best sign)
            result['web_s'] = round(time.monotonic() - t0, 1)
            limit = min(limit, time.monotonic() - t0 + 30)
            screenshot(work, os.path.join(outdir, f'{label}-webstart.png'))
        if last.replace('.', '', 1).isdigit():
            ready_wall = time.monotonic() - t0
            result['ready'] = True
            result['wall_s'] = round(ready_wall, 1)
            result['uptime_s'] = float(last)
            break
        time.sleep(0.25)
    if not result['ready'] and 'web_s' in result:
        result['approx'] = True
    print(json.dumps(result), flush=True)
    if vm.poll() is None:
        time.sleep(4)   # let the sign-in screen settle, then look at it
        screenshot(work, os.path.join(outdir, f'{label}-signin.png'))
        if ser.run('true', timeout=10) is not None:
            ser.run(REPORT.strip().replace('\n', '; '), timeout=120)
            if a.order:
                n = ser.run(ORDER.strip(), timeout=600)
                print('boot files:', n, flush=True)
            dev = (ser.run('readlink -f /dev/disk/by-id/virtio-LOSREPORT', timeout=10) or '').split('\n')[-1].strip()
            if dev.startswith('/dev/'):
                size = ser.run(f'cd /tmp && tar czf rep.tgz rep && dd if=rep.tgz of={dev} bs=1M conv=fsync 2>/dev/null && stat -c %s rep.tgz', timeout=120)
                result['report_bytes'] = int(size.split()[-1]) if size and size.split()[-1].isdigit() else 0
            ser.run('systemctl poweroff', timeout=5)
        for _ in range(60):
            if vm.poll() is not None:
                break
            time.sleep(1)
        if vm.poll() is None:
            vm.kill()
    vm.wait()
    # the report: a gzip'd tar written straight onto the blank disk
    try:
        n = result.get('report_bytes', 0)
        with open(outdisk, 'rb') as f:
            data = f.read(n)
        tgz = os.path.join(work, 'report.tgz')
        with open(tgz, 'wb') as f:
            f.write(data)
        with tarfile.open(tgz, 'r:gz') as t:
            for m in t.getmembers():
                if m.isfile() and '/' in m.name:
                    m.name = label + '-' + m.name.split('/', 1)[1]
                    t.extract(m, outdir)
    except Exception as e:
        print('no report:', e)
    os.remove(outdisk)
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('work')
    ap.add_argument('out')
    ap.add_argument('--uefi', action='store_true')
    ap.add_argument('--usb', action='store_true')
    ap.add_argument('--boots', type=int, default=1)
    ap.add_argument('--mem', type=int, default=4096)
    ap.add_argument('--cpus', type=int, default=2)
    ap.add_argument('--mbps', type=float, default=0, help='limit reading speed (MB/s), like a USB stick')
    ap.add_argument('--timeout', type=int, default=300)
    ap.add_argument('--name', default='')
    ap.add_argument('--order', action='store_true')
    ap.add_argument('--iso', default='', help='an existing test ISO (made by an earlier run) to reuse')
    ap.add_argument('--from-iso', default='', help='test this LaunchOS.iso (built elsewhere) instead of WORKDIR\'s')
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    work = os.path.abspath(os.path.join(a.work, 'boottest'))
    os.makedirs(work, exist_ok=True)
    iso = a.iso or os.path.join(work, 'test.iso')
    if not os.path.exists(iso):
        make_test_iso(os.path.abspath(a.work), iso, os.path.abspath(a.from_iso) if a.from_iso else '')
    disk = iso
    if a.usb:   # a pretend 8 GB USB stick with the image written to it (like Etcher or the flasher)
        disk = os.path.join(work, 'stick.img')
        shutil.copy(iso, disk)
        with open(disk, 'r+b') as f:
            f.truncate(8 * 1024 ** 3)
    name = a.name or ('uefi' if a.uefi else 'bios') + ('-usb' if a.usb else '-cd')
    results = []
    for i in range(a.boots):
        results.append(boot_once(a, disk, work, a.out, f'{name}-boot{i + 1}'))
    if a.usb:
        os.remove(disk)
    with open(os.path.join(a.out, name + '.json'), 'w') as f:
        json.dump(results, f, indent=1)
    ok = all(r.get('ready') or r.get('approx') for r in results)
    print('RESULT', name, json.dumps(results))
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
