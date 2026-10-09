// Checks run when the flasher is built (on a Windows machine on GitHub), written to a log file.
using System;
using System.IO;
using System.IO.Compression;
using System.Linq;
using System.Text;
using System.Threading;

namespace LaunchOSFlasher
{
    static class SelfTest
    {
        static StreamWriter log;
        static int failed;

        static void Check(bool ok, string what)
        {
            log.WriteLine((ok ? "ok    " : "FAIL  ") + what);
            if (!ok) failed++;
        }

        /// <summary>A pretend LaunchOS image: an ISO 9660 header and some data.</summary>
        public static byte[] FakeIso(string version, int size = 4 << 20)
        {
            var b = new byte[size];
            new Random(7).NextBytes(b);
            int o = Images.PvdOffset;
            b[o] = 1;
            Encoding.ASCII.GetBytes("CD001").CopyTo(b, o + 1);
            Encoding.ASCII.GetBytes("LAUNCHOS".PadRight(32)).CopyTo(b, o + 40);
            Encoding.ASCII.GetBytes((version == "" ? "" : "LAUNCHOS " + version).PadRight(128)).CopyTo(b, o + 574);
            return b;
        }

        public static int Run(string logPath)
        {
            using (log = new StreamWriter(logPath))
            {
                try
                {
                    log.WriteLine("LaunchOS Flasher " + Program.Version);
                    Check(Images.ParseHeader(FakeIso("1.0"), out string v) && v == "1.0", "reads the version from a LaunchOS 1.0 image");
                    Check(Images.ParseHeader(FakeIso(""), out v) && v == "", "recognizes an older LaunchOS (no version)");
                    var notIso = new byte[65536];
                    Check(!Images.ParseHeader(notIso, out v), "a blank drive isn't LaunchOS");
                    Check(Images.CompareVersions("0.9", "1.0") < 0 && Images.CompareVersions("1.10", "1.9") > 0 && Images.CompareVersions("", "0.1") < 0 && Images.CompareVersions("v1.0", "1.0") == 0, "compares versions");

                    string dir = Path.Combine(Path.GetTempPath(), "losflash-test");
                    Directory.CreateDirectory(dir);
                    string iso = Path.Combine(dir, "LaunchOS.iso"), zip = Path.Combine(dir, "LaunchOS.zip");
                    File.WriteAllBytes(iso, FakeIso("1.2", 3 << 20));
                    var info = Images.Inspect(iso);
                    Check(info.IsLaunchOS && info.Version == "1.2" && info.Length == 3 << 20 && !info.InZip, "inspects an ISO file");
                    if (File.Exists(zip)) File.Delete(zip);
                    using (var z = ZipFile.Open(zip, ZipArchiveMode.Create))
                    {
                        z.CreateEntryFromFile(iso, "LaunchOS.iso");
                        z.CreateEntry("LaunchOS.vbox");
                    }
                    info = Images.Inspect(zip);
                    Check(info.IsLaunchOS && info.Version == "1.2" && info.Length == 3 << 20 && info.InZip, "finds LaunchOS.iso inside LaunchOS.zip");
                    using (var s = Images.Open(info, out IDisposable owner))
                    {
                        var all = new byte[info.Length];
                        int got = Images.ReadFully(s, all);
                        owner.Dispose();
                        Check(got == info.Length && all.SequenceEqual(File.ReadAllBytes(iso)), "reads the whole image out of the zip");
                    }
                    var rel = Releases.Parse("{\"tag_name\":\"v1.0\",\"html_url\":\"https://github.com/x/y/releases/tag/v1.0\",\"assets\":[{\"name\":\"LaunchOS.zip\",\"size\":5,\"browser_download_url\":\"https://a/LaunchOS.zip\"},{\"name\":\"LaunchOS.iso\",\"size\":1700000000,\"browser_download_url\":\"https://a/LaunchOS.iso\"},{\"name\":\"LaunchOS-Flasher.exe\",\"size\":9,\"browser_download_url\":\"https://a/f.exe\"}]}");
                    Check(rel != null && rel.Version == "1.0" && rel.IsoUrl == "https://a/LaunchOS.iso" && !rel.IsZip && rel.IsoSize == 1700000000 && rel.FlasherUrl == "https://a/f.exe", "reads a GitHub release");
                    var old = Releases.Parse("{\"tag_name\":\"v0.9\",\"assets\":[{\"name\":\"LaunchOS.zip\",\"size\":5,\"browser_download_url\":\"https://a/LaunchOS.zip\"}]}");
                    Check(old != null && old.IsZip && old.IsoUrl == "https://a/LaunchOS.zip", "a release with only the zip is used through the zip");
                    Check(Releases.Parse("{\"tag_name\":\"v1.0\",\"assets\":[]}") == null, "a release without an ISO isn't offered");
                    var latest = Releases.Latest().Result;
                    log.WriteLine("info  newest on GitHub: " + (latest.Item1 != null ? latest.Item1.Version + " " + latest.Item1.IsoUrl + " sha " + latest.Item1.IsoSha256 : latest.Item2));
                    var disks = Drives.All(out bool windowsFound);
                    foreach (var d in disks) log.WriteLine("info  drive " + d.Number + ": " + d.Label + " bus " + d.Bus + " sector " + d.SectorSize + (d.HasWindows ? " (Windows)" : "") + (d.HasLaunchOS ? " has " + Images.Describe(d.LaunchOSVersion) : ""));
                    Check(disks.Count > 0 && disks.All(d => d.Size > 0 && d.SectorSize > 0), "sees the PC's drives, with their sizes");
                    Check(windowsFound && disks.Count(d => d.HasWindows) == 1, "finds the drive Windows is on");
                    var offered = Drives.List(true, out string problem);
                    Check(problem == "" && offered.All(d => !d.HasWindows && (d.Bus == Drives.BusUsb || d.Bus == Drives.BusSd || d.Bus == Drives.BusMmc)),
                        "only USB drives and memory cards are offered, never the Windows drive (" + offered.Count + " offered here)");
                }
                catch (Exception e)
                {
                    log.WriteLine("FAIL  " + e);
                    failed++;
                }
                log.WriteLine(failed == 0 ? "all good" : failed + " failed");
            }
            return failed == 0 ? 0 : 1;
        }

        public static int MakeFake(string path, string version)
        {
            File.WriteAllBytes(path, FakeIso(version, 24 << 20));
            return 0;
        }

        /// <summary>Writes an image to a test VHD file's disk and checks it. Only a small virtual disk made from
        /// the named VHD file can be written this way: never a real drive.</summary>
        public static int WriteTest(string vhd, string image, string logPath)
        {
            using (log = new StreamWriter(logPath))
            {
                try
                {
                    int disk = Drives.DiskOfVhd(vhd);
                    log.WriteLine("test disk " + vhd + " is disk " + disk);
                    var d = Drives.All(out _).FirstOrDefault(x => x.Number == disk) ?? throw new Exception("no disk " + disk);
                    if (d.Bus != Drives.BusVirtual || d.Size > (1L << 30) || d.HasWindows) throw new Exception("disk " + disk + " isn't a small test disk (bus " + d.Bus + ")");
                    Check(!Drives.List(true, out _).Any(x => x.Number == disk), "a virtual disk isn't offered as a USB drive");
                    log.WriteLine("writing " + image + " to " + d.Label + " (bus " + d.Bus + ", volumes " + d.Volumes.Count + ")");
                    var info = Images.Inspect(image);
                    var w = new Writer();
                    string last = "";
                    w.Progress = (step, done, total) => { if (step != last) { log.WriteLine("  " + step); last = step; } };
                    var t0 = DateTime.Now;
                    w.Write(d, info, true, CancellationToken.None, testDisk: true);
                    log.WriteLine("written and checked in " + (DateTime.Now - t0).TotalSeconds.ToString("0.0") + " s");
                    Drives.ReadLaunchOS(d);
                    Check(d.HasLaunchOS && d.LaunchOSVersion == info.Version, "the drive now reads as " + Images.Describe(d.LaunchOSVersion));
                }
                catch (Exception e)
                {
                    log.WriteLine("FAIL  " + e);
                    failed++;
                }
                log.WriteLine(failed == 0 ? "all good" : failed + " failed");
            }
            return failed == 0 ? 0 : 1;
        }
    }
}
