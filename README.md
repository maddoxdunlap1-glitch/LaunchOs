# LaunchOS

![LaunchOS boot screen](assets/boot-preview.gif)

A console-style Linux test build with an Xbox-like home screen, side menu, docked Discord preview, and power menu. It boots to a spinning ferris wheel, then the home screen, and runs live from an ISO in VirtualBox.

## Download

Get **LaunchOS.zip** from the [Releases](../../releases) page. It contains:

- `LaunchOS.iso`: the live system (boots in BIOS and UEFI)
- `LaunchOS.vbox`: a ready-made VirtualBox machine

## Run it in VirtualBox

1. Unzip `LaunchOS.zip` into one folder. Keep the `.iso` and `.vbox` together.
2. In VirtualBox, choose **Machine → Add…** and pick `LaunchOS.vbox`.
3. Start the machine and click inside the window.

The machine uses 2 GB RAM, 2 CPUs, VMSVGA graphics and boots from the DVD.

## Controls

| Action | Keyboard | Controller |
| --- | --- | --- |
| Move | Arrow keys | D-pad or left stick |
| Select | Enter | A |
| Back | Esc | B |
| Side menu | M | Menu or Xbox button |

Shut down or restart from **Side menu → Settings → Power**.

## Notes

- This is a live test build. Nothing is saved between boots.
- Games, Steam and Wine aren't installed yet. Discord is a visual preview.
- Debug console: press Ctrl+Alt+F2 and log in as `root`, password `launchos`.
