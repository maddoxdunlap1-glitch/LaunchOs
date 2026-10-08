LaunchOS v0.8: **Store, Terminal and Updates**.

**Store** (new tile on Home and in the top bar)
- Thousands of free apps and games from Flathub: Discord, Spotify, VLC, OBS Studio, Heroic Games Launcher, Prism Launcher (Minecraft), Lutris, RetroArch, Dolphin, Firefox, LibreOffice, GIMP and more.
- Featured picks, shelves (Games, Internet & chat, Music & video, Creative, Work & school, Tools), search, and an Installed list.
- Install, open and uninstall with progress. Apps you install show up on Home with their icons, and run like any other game or app (Super or the Xbox button comes back Home).

**Terminal**
- A full Linux terminal (bash). Copy and paste buttons, bigger and smaller text. It keeps running when you go Home.
- **Admin password** (Settings): set one to use `sudo`. Setting it the first time asks you to press Enter or A, so only someone at the PC can do it. LaunchOS no longer has a fixed root password.

**Updates** (Settings → Updates)
- **LaunchOS updates** straight from its GitHub releases: checks for a newer version, downloads a small update package, checks it, and installs it. From now on you won't need to download the whole zip for most updates.
- **Update your apps** from the Store, and **update the system** (Ubuntu's security fixes).
- Updates need saving to be on (or LaunchOS installed), otherwise they'd be gone at the next start.

**Fixes**
- Install couldn't see a drive that was open in Files. It now closes the drive by itself.
- Install could list a drive with files on it as empty.

Download **LaunchOS.zip**, unzip it, then in VirtualBox choose **Machine > Add** and pick **LaunchOS.vbox**. If you added an older LaunchOS before, remove it first (Machine > Remove > Remove only). Check the version in Settings > About LaunchOS.
