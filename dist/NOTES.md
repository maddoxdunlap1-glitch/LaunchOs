LaunchOS v0.9: **now based on Debian 13**, with a **sign-in screen**, **real app icons** and **real apps from Setup**.

**Debian 13 inside**
- LaunchOS is rebuilt on Debian 13 "trixie" (Linux 6.12, Mesa 25, Wine 10). Everything from 0.8 works the same: Home, Files, Store, Terminal, Updates, Steam, Windows programs, Wi-Fi, saving and Install.
- **Update the system** in Settings → Updates now installs Debian's security fixes.
- From a USB stick, saving still turns on by itself the first time it starts.

**Sign-in screen**
- LaunchOS starts at a sign-in screen with your name, color, clock and power options.
- Set a password in **Settings → Password** and only you can sign in. You can turn the sign-in question off and still use the password for `sudo`.
- **Lock** (Settings → Power) keeps your apps running behind the sign-in screen. **Sign out** closes them.

**Real apps, picked in Setup**
- Setup and **Settings → Apps on Home** offer Discord, Spotify, FreeTube, Roblox, Minecraft (Prism Launcher), Heroic, OBS Studio and VLC. The ones you tick download from Flathub as real apps, not websites. Their Home tiles show the download, and an app you haven't got yet says **Get**.
- In the side menu, **Discord** opens the Discord app. The web version beside Home is still there.

**Real icons everywhere**
- Apps show their own icons, and LaunchOS's own apps, settings, folders and file types have full-color icons.

**Fixes**
- The Browser could open to a blank page.
- Settings → About LaunchOS → **Open-source credits**.

**Coming from 0.8?** 0.9 is a fresh start, so Settings → Updates can't update 0.8 to it. Download **LaunchOS.zip** and write `LaunchOS.iso` to your USB stick again, or in VirtualBox remove the old machine (Machine > Remove > Remove only) and add the new **LaunchOS.vbox**. Check the version in Settings > About LaunchOS.
