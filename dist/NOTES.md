LaunchOS v0.6: **Steam, Wine, Roblox, FreeTube, Wi-Fi, saving, USB boot and installing**, plus a round of bug fixes.

**Games and apps**
- **Steam** (with Proton for Windows games) is built in. The first time you open it, Steam downloads itself from Valve.
- **Windows programs**: run .exe and .msi files with Wine, from Downloads or a USB drive. The browser can now download files.
- **Roblox** (through Sober) and **FreeTube** download from Flathub the first time you open them.
- One game or app runs at a time, like a console. **Super or the Xbox button** goes Home from inside any app or game; Ctrl+click the tile to Resume or End task.

**Saving and installing**
- **VirtualBox**: the included LaunchOS.vbox now has a save disk (LaunchOS-data.vdi), so your settings, sign-ins, downloads and games are kept.
- **USB stick**: write LaunchOS.iso with balenaEtcher or Rufus (choose DD mode). It boots on BIOS and UEFI PCs, and uses the stick's free space for saving automatically. Secure Boot must be off.
- **Install LaunchOS** (Settings) puts it on a drive in your PC. It erases that drive and asks twice first.

**Also new**
- **Wi-Fi** in Settings: scan, join with a password, forget.
- **Discord** opens as a portrait panel beside Home (side menu > Chat).
- Real graphics acceleration on AMD, Intel and NVIDIA PCs (VirtualBox keeps software drawing).
- Game sound through PipeWire; drivers and firmware for common PC graphics, Wi-Fi and Bluetooth chips.
- Setup's app picks now choose which apps show on Home.

**Fixes**: Setup could get stuck if you pressed buttons quickly; pop-ups could leave the side menu in a broken state; controller buttons held while returning Home counted twice; the Menu key showed a copy/paste menu; misleading browser errors on downloads; safer handling of requests by the system helper; and more.

Download **LaunchOS.zip**, unzip it, then in VirtualBox choose **Machine > Add** and pick **LaunchOS.vbox**. If you added an older LaunchOS before, remove it first (Machine > Remove > Remove only). Check the version in Settings > About LaunchOS.
