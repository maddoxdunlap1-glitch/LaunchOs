# LaunchOS Flasher

A small Windows program (Windows 10 and 11) that puts LaunchOS on a USB drive.

- **Newest LaunchOS:** it checks GitHub for the newest release, downloads `LaunchOS.iso` and checks
  its SHA-256 before writing. Or pick a `LaunchOS.iso` or `LaunchOS.zip` you already have.
- **Asks before you write something old:** if the file you picked is older than the newest
  release, or a USB drive you plug in has an older LaunchOS on it, it offers the newest.
- **Safe:** only USB drives and memory cards are listed, never the drive Windows runs from (and
  if it can't tell which drive that is, it lists none). USB hard drives only show when you tick
  "Also show USB hard drives". It asks before erasing, showing what's on the drive, and checks
  again right before writing that it's still the very same drive. It writes the image byte for
  byte and reads it back to check it. Old LaunchOS saves on the drive are erased too. If writing
  stops halfway, the drive is left blank rather than half written.
- **Only checked downloads:** it downloads a release only if it can check it against the release's
  `SHA256SUMS.txt`.
- **Newer flasher:** a banner says when a newer flasher is out.

Windows asks for administrator rights when it starts (writing a whole drive needs them). The
.exe isn't signed, so the first time Windows SmartScreen may say "Windows protected your PC":
choose **More info**, then **Run anyway**.

Built and tested by the *Flasher* GitHub Action (`.github/workflows/flasher.yml`): it builds the
.exe, runs its checks, writes a test image to a virtual disk (with `--write-test-vhd`, which only
ever writes to a small virtual disk made from a VHD file) and compares every byte, checks that an
old save area was cleared, and takes a screenshot of the window. To build it yourself on Windows: `dotnet build LaunchOSFlasher -c Release`
(.NET SDK 6 or later; the .exe runs on the .NET Framework 4.8 that comes with Windows).
