# LaunchOS

![LaunchOS boot screen](assets/boot-preview.gif)

A console-style Linux system with an Xbox-like home screen. It boots to a spinning ferris wheel, then Home. Run it in VirtualBox, from a USB stick, or install it on a PC.

**What's in it**

- **Steam** with Proton for Windows games. Steam downloads itself from Valve the first time you open it.
- **Windows programs**: run .exe and .msi files with Wine, from your Downloads or a USB drive.
- **Roblox** (through Sober) and **FreeTube**: they download from Flathub the first time you open them.
- **Browser**: a lightweight web browser with a start page, shortcuts and downloads. `Ctrl+L` address bar, `Alt+Left` back, `F5` reload, `Ctrl+W` close.
- **System monitor**: live CPU, memory, network and storage, one-minute charts, the busiest processes and per-core load.
- **Setup**: your name and color, time zone, network, sound, screen size, controller test, look, and which apps show on Home.
- **Side menu** (`M`, Super, or the Menu or Xbox button): running apps, Discord as a portrait panel, devices, notifications, and Settings (screen size, sound, network, Wi-Fi, time zone, saving, install, power).
- **Apps keep running** when you go Home. **Ctrl+click** (or right-click) an app for Resume, Restart, End task and Move.

## Download

Get **LaunchOS.zip** from the [latest release](../../releases/latest). It contains:

- `LaunchOS.iso`: the system. Boots as a disc or a USB stick, on BIOS and UEFI.
- `LaunchOS.vbox`: a ready-made VirtualBox machine
- `LaunchOS-data.vdi`: its save disk (starts empty and grows as you use it)

Check which version you're running in **Settings → About LaunchOS**.

## Run it in VirtualBox

1. Unzip `LaunchOS.zip` into one folder. Keep the three files together.
2. In VirtualBox, choose **Machine → Add…** and pick `LaunchOS.vbox`. If you added an older LaunchOS before, remove that one first (**Machine → Remove → Remove only**).
3. Start the machine and click inside the window.

The machine uses 4 GB RAM, 4 CPUs and VMSVGA graphics, and keeps your stuff on its save disk. VirtualBox has no real graphics acceleration here, so games will be slow; for games, use a USB stick.

Making your own VM instead? Set **Type: Linux, Version: Ubuntu (64-bit)** and at least **2048 MB** of memory. LaunchOS is 64-bit and won't start on a 32-bit ("Other") VM.

## Run it from a USB stick

1. Write `LaunchOS.iso` to a USB stick (8 GB or more) with [balenaEtcher](https://etcher.balena.io), or with [Rufus](https://rufus.ie) in **DD mode**. This erases the stick.
2. Turn off **Secure Boot** in your PC's BIOS/UEFI settings.
3. Start the PC from the USB stick (usually F8, F12 or Esc at power-on opens the boot menu).

The first time it starts, LaunchOS uses the free space on the stick for saving, so your settings, sign-ins and games are kept.

## Install it on a PC

Start LaunchOS from a USB stick, then open **Settings → Install LaunchOS** and pick a drive (16 GB or more). **This erases everything on that drive.** LaunchOS asks twice before it starts.

## Controls

| Action | Keyboard / mouse | Controller |
| --- | --- | --- |
| Move | Arrow keys, or point with the mouse | D-pad or left stick |
| Select | Enter or click | A |
| Back | Esc | B |
| Side menu | M or Super (Windows key) | Menu or Xbox button |
| Back to Home from an app or game | Super | Xbox button |
| App options | Ctrl+click, right-click, Menu key | X |

Shut down or restart from **Side menu → Settings → Power**.

## Notes

- Only one game or app (Steam, Roblox, a Windows program…) runs at a time, like on a console. Web apps (YouTube, Discord, Twitch) can run alongside.
- Wi-Fi passwords are typed with a keyboard for now.
- Debug console: press Ctrl+Alt+F2 and log in as `root`, password `launchos`.
