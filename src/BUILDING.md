# How LaunchOS is put together

This folder is LaunchOS's source. Since v0.9 LaunchOS is built on Debian 13; v0.8 and earlier were Ubuntu-based (their scripts are kept in `build/ubuntu-era/`).

## Building

Everything is built on GitHub Actions (this repo's `.github/workflows/`):

1. **Base system** (*Build Debian base*, `build/debian/base.sh` and `packages.txt`): Debian plus every package and Flathub's catalog. Runs whenever those files change and publishes the prerelease `build-debian-base` (`base.squashfs.part*`; join the parts with `cat`).
2. **LaunchOS** (*Build LaunchOS*, run by hand): `build/debian/make-image.sh` adds `ui/`, `rootfs/` and the boot theme to the base and makes `LaunchOS.iso` (hybrid: disc and USB, BIOS and UEFI). Then `tests/ci_boot.py` starts it in QEMU with KVM four ways (BIOS and UEFI, disc and USB stick at 40 MB/s, the USB stick twice so saving is set up and then used), checks it reaches the sign-in screen without errors and times it.
   - *test*: publishes the ISO and the start-up report as the `build-test` prerelease.
   - *release*: also builds the flasher (*Flasher* workflow), the VirtualBox files (`build/debian/make-vbox.sh`) and the update package (`build/debian/make-update.sh`), and publishes the release `v` + `dist/VERSION` with `dist/NOTES.md` as its notes. Only the newest release is kept.
3. **LaunchOS Flasher** (*Flasher*, on every change in `flasher/`): builds `LaunchOS-Flasher.exe` on Windows, runs its checks, writes a test image to a virtual disk and compares every byte. Publishes the `build-flasher` prerelease.
4. **Pro files** (*Pro files*, run by hand): the files the LaunchOS Pro server hands out, signed with the Pro signing key (`pro-server/SETUP.md`).

To build by hand on Debian/Ubuntu: `sudo build/debian/make-image.sh base.squashfs WORKDIR VERSION [fast]`.

Release settings in `dist/`: `VERSION`, `NOTES.md`, `MIN_VERSION` (the oldest LaunchOS that can update to this one through Settings > Updates; older ones are told to download it fresh), optional `FULL` (1: no one can update to it), `APT` (Debian packages an update needs) and `UPDATE_NOTE`.

## Folders

| Folder | What it is |
| --- | --- |
| `ui/` | The launcher: `launch.py` (GTK4 + WebKitGTK 6.0), the pages (`index.html` Home, `login.html` sign-in, `setup.html`, `files.html`, `store.html`, `monitor.html`, `view.html`, `start.html`), `los.js` / `los.css` (shared: the call bridge with browser mocks, looks, wallpapers, the on-screen keyboard), `fsops.py` (copy/move jobs), `walls/` (wallpapers), `icons/`, `img/`. Installed to `/opt/launcher`, owned by root. |
| `rootfs/` | Files put on top of the system image, owned by root: systemd units, udev rule, tmpfiles, sysctl, plymouth settings, sway config, update and Pro settings, and the root scripts in `/usr/local/sbin`. |
| `boot-theme/` | The rocket Plymouth boot theme (`/usr/share/plymouth/themes/launchos`). |
| `art/` | Where the art comes from: `make-art.py` (rocket, boot frames, icon), `walls/*.glsl` (the wallpapers, drawn on the GPU; `walls/export.py` saves them to `ui/walls/`), `preview.py` (the README's boot preview). |
| `pro/` | LaunchOS Pro extras (the live backgrounds), packed by `pro-server/make-pro-files.py`. |
| `build/debian/` | The Debian 13 build (see above). |
| `build/ubuntu-era/` | The scripts that built v0.1–v0.8 on Ubuntu 24.04 (history only). |
| `tests/` | `ci_boot.py` (start-up tests), `every_button.js` (presses every button on every page with the mocks, mouse and keyboard; about an hour), `mock_pro_server.py`, older page tests (`pt16.js`, `pt17.js`, `monkey.js`) and QEMU helpers. |
| `../flasher/` | LaunchOS Flasher for Windows (C#, .NET Framework 4.8). |
| `../pro-server/` | The LaunchOS Pro server (a Cloudflare Worker) and its setup. |

## How it runs

- **Boot:** GRUB (no menu) → kernel + a slim start-up image (no AMD/NVIDIA/network drivers: they load from the system a moment later) → Debian live-boot with `persistence`. GRUB and the start-up image only accept the disc or stick of their own build (`/.disk/live-uuid-*`). A partition labelled `persistence` keeps changes: the VirtualBox save disk, or the free space of the USB stick, which `initramfs-tools/scripts/live-premount/launchos-saving` turns into a save area on the first start. Plymouth shows the rocket. The user is `player` (uid 1000), hostname `launchos`; each PC makes its own machine id on its first start.
- **Session:** `launcher.service` runs `/usr/local/bin/launchos-session` as `player` on tty1 (no display manager, no getty on tty1). It picks hardware or software drawing, then starts sway with `/etc/launchos/sway.conf`, which runs `launchos-inner` (PipeWire, WirePlumber, then `python3 /opt/launcher/launch.py`). Seat access is through `seatd`. It starts at the sign-in page, `login.html`.
- **Pages talk to Python** through `call(action, arg)` in `los.js`, handled in `launch.py` (slow calls in threads). Opened in a normal browser, the pages use mocks instead, which is how the page tests run.
- **Root actions** (power, Wi-Fi, time zone, drives, format, install, Store, updates, password, Pro, gaming mode): the launcher writes a small JSON file into `/run/launchos/requests/` (owned by player). `launchos-helper.path` starts `launchos-helper`, which runs as root, accepts only a fixed list of actions and validates every value; long jobs run through `systemd-run` and write progress to `/run/launchos-status/<job>.json` (root-owned), which the launcher polls.
- **Drives:** USB drives mount under `/media/player` (root-owned 755) through the udev rule and `launchos-drives`. `/usr/local/lib/launchos/disks.py` is shared code: which disk LaunchOS runs from and saves to, what's in use.
- **Store:** Flathub (system install). `launchos-store` runs flatpak on a pseudo-terminal to read progress.
- **Updates:** `launchos-update` reads `/etc/launchos/update.conf` (`url=` the GitHub `releases/latest/download/` folder), downloads `launchos-update-v1.json`, then the version's `launchos-update.tar.gz`, checks SHA-256 and only writes LaunchOS's own files. Needs saving on. `launchos-reconcile` makes sure a save area never hides a newer LaunchOS image. **While the repo is private, these downloads only work once releases are publicly reachable.**
- **LaunchOS Pro:** `launchos-pro` activates a key with the Pro server (`url=` in `/etc/launchos/pro.conf`), downloads the Pro extras to `/opt/launchos-pro` (only if signed with the key in `signing_key=`, see `lib/launchos/signed.py`) and re-checks the key monthly (never turning Pro off for being offline). With Pro, `launchos-game` (gaming mode) runs while a game is open, and early-access updates come from the Pro server.
- **Password:** none by default; root is locked. Setting one goes through `launchos-admin`, which needs a physical key press the first time.
- **Version:** `/etc/launchos-release` (`VERSION=`, `BUILD_DATE=`, `EARLY=` for early-access builds), shown in Settings → About.
