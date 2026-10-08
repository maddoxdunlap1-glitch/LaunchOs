# LaunchOS

![LaunchOS boot screen](assets/boot-preview.gif)

A console-style Linux system, based on Debian, with a controller-friendly Home screen. It boots to a spinning ferris wheel, then Home. Run it in VirtualBox, from a USB stick, or install it on a PC.

**What's in it**

- **Sign-in screen** with your name and color. Set a password in Settings and only you can sign in; **Lock** keeps your apps running behind it.
- **Steam** with Proton for Windows games. Steam downloads itself from Valve the first time you open it.
- **Windows programs**: run .exe and .msi files with Wine, from your Downloads or a USB drive.
- **Real apps, picked in Setup**: Discord, Spotify, FreeTube (YouTube without ads), Roblox (through Sober), Minecraft (through Prism Launcher), Heroic (Epic Games and GOG), OBS Studio and VLC. The ones you pick download from Flathub and show up on Home with their own icons.
- **Browser**: a lightweight web browser with a start page, shortcuts and downloads. `Ctrl+L` address bar, `Alt+Left` back, `F5` reload, `Ctrl+W` close.
- **Files**: your Downloads, Documents, Pictures, Videos and Music, plus USB drives and disks. Copy, move, rename and delete, with progress you can stop. Look at pictures, play videos and music, read text files, and run Windows programs straight from a folder. Open drives inside the PC, eject USB drives safely, and format a drive as exFAT, FAT32, NTFS or ext4.
- **Store**: thousands of free apps and games from Flathub (Discord, Spotify, VLC, OBS, Heroic, Prism Launcher for Minecraft, emulators and more). Installed apps show up on Home.
- **Terminal**: a full Linux terminal. Set a **password** in Settings to use `sudo`.
- **Updates** (Settings → Updates): update LaunchOS straight from its GitHub releases, update your Store apps, and install Debian's security fixes.
- **System monitor**: live CPU, memory, network and storage, one-minute charts, the busiest processes and per-core load.
- **Setup**: your name and color, time zone, network, sound, screen size, controller test, look, and your apps.
- **Side menu** (`M`, Super, or the controller's Menu or Home button): running apps, Discord, devices, notifications, and Settings (screen size, sound, network, Wi-Fi, time zone, apps on Home, password, saving, install, updates, power).
- **Apps keep running** when you go Home. **Ctrl+click** (or right-click) an app for Resume, Restart, End task and Move.

## Download

Get **LaunchOS.zip** from the [latest release](../../releases/latest). It contains:

- `LaunchOS.iso`: the system. Boots as a disc or a USB stick, on BIOS and UEFI.
- `LaunchOS.vbox`: a ready-made VirtualBox machine
- `LaunchOS-data.vdi`: its save disk (starts empty and grows as you use it)
- `LaunchOS-storage.vdi`: a spare empty drive to try Files on (format it in Files first)

Check which version you're running in **Settings → About LaunchOS**.

## Run it in VirtualBox

1. Unzip `LaunchOS.zip` into one folder. Keep the files together.
2. In VirtualBox, choose **Machine → Add…** and pick `LaunchOS.vbox`. If you added an older LaunchOS before, remove that one first (**Machine → Remove → Remove only**).
3. Start the machine and click inside the window.

The machine uses 4 GB RAM, 4 CPUs and VMSVGA graphics, and keeps your stuff on its save disk. VirtualBox has no real graphics acceleration here, so games will be slow; for games, use a USB stick.

Making your own VM instead? Set **Type: Linux, Version: Debian (64-bit)** and at least **2048 MB** of memory. LaunchOS is 64-bit and won't start on a 32-bit ("Other") VM.

## Run it from a USB stick

1. Write `LaunchOS.iso` to a USB stick (8 GB or more) with [balenaEtcher](https://etcher.balena.io), or with [Rufus](https://rufus.ie) in **DD mode**. This erases the stick.
2. Turn off **Secure Boot** in your PC's BIOS/UEFI settings.
3. Start the PC from the USB stick (usually F8, F12 or Esc at power-on opens the boot menu).

The first time it starts, LaunchOS uses the free space on the stick for saving, so your settings, sign-ins and games are kept.

## Install it on a PC

Start LaunchOS from a USB stick, then open **Settings → Install LaunchOS** and pick a drive (16 GB or more). **This erases everything on that drive.** LaunchOS asks twice before it starts.

## Files and drives

Open **Files** from Home. USB drives show up by themselves when you plug them in; drives inside the PC open when you select them. Select a file or folder and press X (or right-click) for Copy, Move, Rename, Delete and more, then go to another folder or drive and choose **Paste here**. Press X on a drive to **Eject** it before unplugging, or to **Format** it (exFAT works almost everywhere). Keyboard shortcuts work too: `Ctrl+C`, `Ctrl+X`, `Ctrl+V`, `Delete`, `F2` to rename, `Space` to select.

## Controls

| Action | Keyboard / mouse | Controller |
| --- | --- | --- |
| Move | Arrow keys, or point with the mouse | D-pad or left stick |
| Select | Enter or click | A |
| Back | Esc | B |
| Side menu | M or Super (Windows key) | Menu or Home button |
| Back to Home from an app or game | Super | Home button |
| App options | Ctrl+click, right-click, Menu key | X |

Lock, sign out, shut down or restart from **Side menu → Settings → Power**.

## Notes

- Only one game or app (Steam, Discord, Roblox, a Windows program…) runs at a time, like on a console. The Browser and Terminal can run alongside.
- Wi-Fi passwords are typed with a keyboard for now.
- Password: set one in **Settings → Password** (the first time, it asks you to press Enter or A to confirm). It's asked for at the sign-in screen (you can turn that off) and for `sudo` in the Terminal. There's no default root password. Type it with a keyboard for now.
- Text console: press Ctrl+Alt+F2 and log in as `player` with your password.
- Coming from LaunchOS 0.8 (based on Ubuntu)? 0.9 is a fresh start on Debian: download the new LaunchOS.zip and write it to your USB stick again, or add the new LaunchOS.vbox. Saves from 0.8 aren't used.
- Updates and Store apps are kept only when saving is on (or LaunchOS is installed).

## LaunchOS Pro

*Coming soon.* LaunchOS is free, and everything above stays free. **LaunchOS Pro** will be an optional $5 one-time unlock that adds extra themes and animated Home backgrounds, game tweaks (performance mode, FPS overlay switch), early access to new versions and a supporter badge. One key will work on up to 5 PCs and cover every future version. It isn't on sale yet; see the [LaunchOS site](docs/index.html) for news.

## Credits and trademarks

LaunchOS is built on Debian and many open-source projects (Linux, sway, GTK, WebKitGTK, Wine, Flatpak and others); see Settings → About LaunchOS → Open-source credits. LaunchOS is an independent project and is not made by or endorsed by Debian, Valve or any other company named here. Steam is a trademark of Valve Corporation.
