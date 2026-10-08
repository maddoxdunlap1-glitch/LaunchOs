# How LaunchOS is put together

This folder is LaunchOS's source. Since v0.9 LaunchOS is built on Debian 13; v0.8 and earlier were Ubuntu-based (their scripts are kept in `build/ubuntu-era/`).

## Building (Debian 13)

1. **Base system** (`build/debian/base.sh`, `packages.txt`): Debian plus every package and Flathub's catalog. Built by the *Build Debian base* GitHub Action whenever those files change, and published as the prerelease `build-debian-base` (`base.squashfs.part*`; join the parts with `cat`).
2. **Image**: `sudo build/debian/make-image.sh base.squashfs WORKDIR 0.9 [fast]` adds `ui/`, `rootfs/` and the boot theme, and makes `WORKDIR/LaunchOS.iso` (hybrid: disc and USB, BIOS and UEFI).
3. **VirtualBox files**: `sudo build/debian/make-vbox.sh OUTDIR` (the machine, an empty save disk labelled `persistence`, a spare drive).
4. **Update package**: `build/debian/make-update.sh 0.9 dist/update` (`FULL=1` when older versions can't update to it).
5. **Release**: zip the ISO and VirtualBox files, split into 90 MB `dist/LaunchOS.zip.part*`, write `dist/PARTS`, `dist/SHA256`, `dist/VERSION`, `dist/NOTES.md`, and push; the *Publish LaunchOS release* Action does the rest.

The *Smoke test* Action installs apps from Flathub through `launchos-store` on the base system (this workspace can't reach Flathub).

## Folders

| Folder | What it is |
| --- | --- |
| `ui/` | The launcher: `launch.py` (GTK4 + WebKitGTK 6.0), the pages (`index.html` Home, `files.html`, `store.html`, `setup.html`, `monitor.html`, `view.html`, `start.html`), `los.js` / `los.css`, `fsops.py` (copy/move jobs). Installed to `/opt/launcher`, owned by root. |
| `rootfs/` | Files copied on top of the system image (`cp -a rootfs/. <image root>/`): systemd units, udev rule, tmpfiles, sway config, update config, and the root scripts in `/usr/local/sbin`. |
| `boot-theme/` | The ferris-wheel Plymouth boot theme (`/usr/share/plymouth/themes/launchos`) and the script that drew its images. |
| `build/debian/` | The Debian 13 build (see above). |
| `build/ubuntu-era/` | The scripts that built v0.1–v0.8 on Ubuntu 24.04, in the order they were made. **Their paths point to an old temporary folder (`O=` / `W=` / `R=` at the top) and must be changed before use.** Also the image's package list (`packages-manual.txt`), foreign architectures (i386), masked units, GRUB menu, casper settings and initramfs modules. |
| `tests/` | Playwright page tests (`pt16.js`, `pt17.js`, `monkey.js` random input), QEMU helpers (`vm6.sh` starts a VM; `push.py`, `sh.py`, `qmp.py`, `serlog.py` drive it over the serial console), stress scripts. |

## How it runs

- **Boot:** GRUB → kernel + initrd → casper live system (Ubuntu) with `persistent`: a partition labelled `casper-rw` or `writable` keeps changes. Plymouth shows the ferris wheel. The user is `player` (uid 1000), hostname `launchos`.
- **Session:** `launcher.service` runs `/usr/local/bin/launchos-session` as `player` on tty1 (no display manager, no getty on tty1). It picks hardware or software drawing, then starts sway with `/etc/launchos/sway.conf`, which runs `launchos-inner` (PipeWire, WirePlumber, then `python3 /opt/launcher/launch.py`). Seat access is through `seatd`.
- **Pages talk to Python** through `call(action, arg)` in `los.js`, handled in `launch.py`.
- **Root actions** (power, Wi-Fi, time zone, drives, format, install, Store, updates, admin password): the launcher writes a small JSON file into `/run/launchos/requests/` (owned by player). `launchos-helper.path` (DirectoryNotEmpty) starts `launchos-helper.service`, which runs `/usr/local/sbin/launchos-helper` as root. It accepts only a fixed list of actions and validates every value; long jobs run through `systemd-run` and write progress to `/run/launchos-status/<job>.json` (root-owned), which the launcher polls.
- **Drives:** USB drives mount under `/media/player` (root-owned 755) through the udev rule and `launchos-drives`. Drive jobs share the lock `/run/launchos-status/.drives.lock`. `/usr/local/lib/launchos/disks.py` is shared code: which disk LaunchOS runs from and saves to, what's in use.
- **Store:** Flathub (system install). The catalog is read from `/var/lib/flatpak/appstream/flathub/x86_64/active/appstream.xml.gz` and its icons. `launchos-store` runs flatpak on a pseudo-terminal to read progress.
- **Updates:** `launchos-update` reads `/etc/launchos/update.conf` (`url=` the GitHub `releases/latest/download/` folder), downloads `launchos-update.json`, then the version-specific `launchos-update.tar.gz`, checks SHA-256 and only writes under allowed paths (`/opt/launcher`, `/usr/local`, `/etc/launchos`, a few units). Needs saving on. `launchos-reconcile.service` fixes a save area that holds an older LaunchOS than the image. `build/ubuntu-era/make-update.sh` builds the package. **The repo is private, so these downloads only work once releases are publicly reachable.**
- **Admin password:** none by default; root is locked. Setting one in Settings goes through `launchos-admin`, which needs a physical key press for the first set and writes `/etc/sudoers.d/launchos-player` and `/etc/launchos/admin-set`.
- **Version:** `/etc/launchos-release` (`VERSION=`, `BUILD_DATE=`), shown in Settings → About.

## What changed from Ubuntu (done in v0.9)

- **casper** (live boot, persistence, `username=`/`hostname=` boot options, `/etc/casper.conf`) → Debian's **live-boot** / **live-config** (`boot=live`, `persistence` with a `persistence.conf`, `live-config.username=player`). `launchos-usb-saving`, `launchos-install`, `launchos-reconcile` and `disks.py` look for casper's partition labels and paths (`casper-rw`, `writable`, `/cdrom/casper`); search for `casper` across `rootfs/` and `ui/`.
- **Image layout:** `/casper/vmlinuz`, `/casper/initrd`, `/casper/filesystem.squashfs` → `/live/...`. The hybrid ISO (BIOS + UEFI, works from USB written with Etcher or Rufus DD mode) is built with xorriso in `build/ubuntu-era/build6.sh`; `live-build` can produce the same.
- **Packages:** `packages-manual.txt` lists Ubuntu names. Most are the same on Debian. Differences to check: `steam-installer` (Debian `contrib`/`non-free`), `linux-firmware` → `firmware-linux` / `firmware-misc-nonfree` / `firmware-amd-graphics` / `firmware-iwlwifi` etc. (`non-free-firmware`), `intel-microcode` / `amd64-microcode` (`non-free-firmware`), `gir1.2-vte-3.91` and `gir1.2-webkit-6.0` (Debian 13 has both), `casper` (drop). i386 must be enabled for Steam and Wine.
- **Updates button "Install Ubuntu's security fixes"** (`launchos-update system`, text in `index.html`) → Debian security updates.
- **Branding:** remove "Ubuntu" from pages, README, GRUB text and the VirtualBox "Ubuntu (64-bit)" type note (Debian (64-bit) instead).
