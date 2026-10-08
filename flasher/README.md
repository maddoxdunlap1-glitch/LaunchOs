# LaunchOS Flasher

A small Windows program (Windows 10 and 11) that puts LaunchOS on a USB drive.

- **Newest LaunchOS:** it checks GitHub for the newest release, downloads `LaunchOS.iso` and checks
  its SHA-256 before writing. Or pick a `LaunchOS.iso` or `LaunchOS.zip` you already have.
- **Asks before you write something old:** if the file you picked is older than the newest
  release, or a USB drive you plug in has an older LaunchOS on it, it offers the newest.
- **Safe:** only USB drives and memory cards are listed, never the drive Windows runs from. It
  asks before erasing, writes the image byte for byte, then reads it back to check it.
- **Newer flasher:** a banner says when a newer flasher is out.

Windows asks for administrator rights when it starts (writing a whole drive needs them). The
.exe isn't signed, so the first time Windows SmartScreen may say "Windows protected your PC":
choose **More info**, then **Run anyway**.

Built and tested by the *Flasher* GitHub Action (`.github/workflows/flasher.yml`): it builds the
.exe, runs its checks, writes a test image to a virtual disk and compares every byte, and takes a
screenshot of the window. To build it yourself on Windows: `dotnet build LaunchOSFlasher -c Release`
(.NET SDK 6 or later; the .exe runs on the .NET Framework 4.8 that comes with Windows).
