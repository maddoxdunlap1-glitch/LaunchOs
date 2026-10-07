LaunchOS v0.7: **Files**, for your downloads, USB drives and disks, plus stress testing and a round of fixes.

**Files** (new tile on Home, also in the top bar and side menu)
- Browse Downloads, Documents, Pictures, Videos and Music, and every USB drive or disk.
- **Copy, move, rename and delete**, one item or many (Select, or Ctrl/Shift+click). Progress shows files, size and speed, keeps going if you go Home, and can be stopped.
- Safe copying: nothing is half-written if you stop or the drive is pulled out, a move removes the originals only once the copy is written, and you get a plain warning when a drive is full or a file is too big for FAT32.
- **Drives**: USB drives open by themselves when plugged in. Drives inside the PC open when you select them (a Windows drive that wasn't shut down cleanly opens read-only). **Eject** makes a USB drive safe to unplug.
- **Format** a drive as exFAT, FAT32, NTFS or ext4. LaunchOS asks twice first, and never lets you format the drive it runs from or saves to.
- Look at pictures (left and right for the next one), play videos and music, read text files, open PDFs, and run Windows programs straight from a folder.
- Works with a controller: A opens, B goes back, X (or the Menu key, or right-click) shows options.

**VirtualBox**: LaunchOS.vbox now has a spare empty 64 GB drive (LaunchOS-storage.vdi) to try Files on. Open it in Files and format it.

**Fixes from stress testing**
- After typing in a pop-up (like a Wi-Fi password), the left and right keys could stop working on Home.
- A faded message could stay faintly on screen.
- Install could list a drive with files on it as empty.
- Requests to the system helper sent close together could be lost; they're now queued.
- Opening, ejecting and formatting drives are checked again as the system user, so a hostile request or link can't touch the system or save drive.
- Script errors on LaunchOS's own pages are now logged (~/.cache/launchos/ui-errors.log).

Download **LaunchOS.zip**, unzip it, then in VirtualBox choose **Machine > Add** and pick **LaunchOS.vbox**. If you added an older LaunchOS before, remove it first (Machine > Remove > Remove only). Check the version in Settings > About LaunchOS.
