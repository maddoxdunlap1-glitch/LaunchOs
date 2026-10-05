# LaunchOS

![LaunchOS boot screen](assets/boot-preview.gif)

A console-style Linux test build with an Xbox-like home screen. It boots to a spinning ferris wheel, then the home screen, and runs live from an ISO in VirtualBox.

**What's in it**

- **Browser**: a lightweight web browser with a start page and shortcuts (YouTube, Discord, Twitch and more). `Ctrl+L` address bar, `Alt+Left` back, `F5` reload, `Ctrl+W` back to the home screen.
- **Setup**: walks through your name and color, time zone, network, sound, screen size, controllers and devices, look, and the apps you want.
- **System monitor**: live CPU, memory, network and storage with one-minute charts, the busiest processes and per-core load.
- **Side menu** (`M` or the Menu button): devices, notifications, and settings for screen size, sound, network, time zone and power.

It's a live system: changes reset when you shut down.

## Download

Get **LaunchOS.zip** from the [latest release](../../releases/latest). Check which version you are running in **Settings → About LaunchOS**. It contains:

- `LaunchOS.iso`: the live system (boots in BIOS and UEFI)
- `LaunchOS.vbox`: a ready-made VirtualBox machine

## Run it in VirtualBox

1. Unzip `LaunchOS.zip` into one folder. Keep the `.iso` and `.vbox` together.
2. In VirtualBox, choose **Machine → Add…** and pick `LaunchOS.vbox`.
3. Start the machine and click inside the window.

The machine uses 2 GB RAM, 2 CPUs, VMSVGA graphics and boots from the DVD.

Making your own VM instead? Set **Type: Linux, Version: Ubuntu (64-bit)** and at least **2048 MB** of memory. LaunchOS is 64-bit and won't start on a 32-bit ("Other") VM.

## Controls

| Action | Keyboard | Controller |
| --- | --- | --- |
| Move | Arrow keys | D-pad or left stick |
| Select | Enter | A |
| Back | Esc | B |
| Side menu | M | Menu or Xbox button |

The mouse works too: point at a tile to highlight it, click to open it.

Shut down or restart from **Side menu → Settings → Power**.

## Notes

- This is a live test build. Nothing is saved between boots.
- Games, Steam and Wine aren't installed yet. Discord is a visual preview.
- Debug console: press Ctrl+Alt+F2 and log in as `root`, password `launchos`.
