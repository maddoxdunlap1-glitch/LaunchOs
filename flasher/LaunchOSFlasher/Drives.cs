// The drives LaunchOS can be written to: USB drives and memory cards only, never the drive
// Windows runs from, never a drive inside the PC. USB hard drives (big drives that aren't
// removable, often holding backups) only show when asked for.
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Runtime.InteropServices;
using System.Text;
using Microsoft.Win32.SafeHandles;

namespace LaunchOSFlasher
{
    class Drive
    {
        public int Number;
        public string Model = "";
        public string Serial = "";
        public long Size;
        public int SectorSize;
        public int Bus;                     // 7 USB, 12 SD, 13 MMC, 15 a virtual disk file
        public bool Removable;
        public bool HasWindows;             // Windows is on it
        public List<string> Letters = new List<string>();
        public List<string> Names = new List<string>();     // the volumes' names ("BACKUP")
        public List<string> Volumes = new List<string>();   // \\?\Volume{...} names
        public bool HasLaunchOS;
        public string LaunchOSVersion = "";

        /// <summary>What makes this drive this drive: checked again just before writing, so a drive that was
        /// swapped (or a disk that took its number) is never written by mistake.</summary>
        public string Identity => Bus + "|" + Model + "|" + Serial + "|" + Size + "|" + SectorSize;

        /// <summary>A USB hard drive or SSD rather than a stick: not removable and big.</summary>
        public bool IsHardDrive => !Removable && Size > 256L * 1000 * 1000 * 1000;

        public string Label
        {
            get
            {
                string letters = Letters.Count > 0 ? " (" + string.Join(", ", Letters.Select(l => l.TrimEnd('\\'))) + ")" : "";
                return (Model.Length > 0 ? Model : "Drive " + Number) + " · " + Images.Size(Size) + letters;
            }
        }

        /// <summary>For the "erase it?" question: the drive and the names of what's on it.</summary>
        public string Description => Label + (Names.Count > 0 ? "\nOn it now: " + string.Join(", ", Names.Distinct().Select(n => "\"" + n + "\"")) : "");
    }

    static class Drives
    {
        public const int BusUsb = 7, BusSd = 12, BusMmc = 13, BusVirtual = 15;

        static SafeFileHandle OpenDisk(int n, uint access) =>
            Native.CreateFile(@"\\.\PhysicalDrive" + n, access, Native.FILE_SHARE_READ | Native.FILE_SHARE_WRITE, IntPtr.Zero, Native.OPEN_EXISTING, 0, IntPtr.Zero);

        /// <summary>One disk, as it is right now (null if there's no disk, or no card in a card reader).</summary>
        public static Drive Probe(int n)
        {
            using (var h = OpenDisk(n, 0))
            {
                if (h.IsInvalid) return null;
                var d = new Drive { Number = n };
                if (!Native.Describe(h, out d.Bus, out d.Removable, out d.Model, out d.Serial)) return null;
                if (!Native.Geometry(h, out d.Size, out d.SectorSize)) return null;
                return d;
            }
        }

        /// <summary>The identity of disk n read from an open handle (used by the writer on its own handle).</summary>
        public static string IdentityOf(SafeFileHandle h)
        {
            if (!Native.Describe(h, out int bus, out _, out string model, out string serial)) return "";
            if (!Native.Geometry(h, out long size, out int sector)) return "";
            return bus + "|" + model + "|" + serial + "|" + size + "|" + sector;
        }

        /// <summary>The volume Windows runs from (\\?\Volume{...}), or "".</summary>
        static string WindowsVolume()
        {
            try
            {
                var root = new StringBuilder(260);
                if (!Native.GetVolumePathName(Environment.SystemDirectory, root, root.Capacity)) return "";
                var name = new StringBuilder(260);
                if (!Native.GetVolumeNameForVolumeMountPoint(root.ToString(), name, name.Capacity)) return "";
                return name.ToString().TrimEnd('\\');
            }
            catch { return ""; }
        }

        /// <summary>Every disk Windows sees, with its volumes, and which one has Windows on it.</summary>
        public static List<Drive> All(out bool windowsFound)
        {
            var disks = new Dictionary<int, Drive>();
            for (int i = 0; i < 64; i++)
            {
                var d = Probe(i);
                if (d != null) disks[i] = d;
            }
            string windows = WindowsVolume();
            windowsFound = false;
            foreach (var v in AllVolumes())
            {
                foreach (int disk in v.Item2)
                {
                    if (!disks.TryGetValue(disk, out Drive d)) continue;
                    d.Volumes.Add(v.Item1);
                    d.Letters.AddRange(v.Item3);
                    if (v.Item4 != "") d.Names.Add(v.Item4);
                    if (windows != "" && string.Equals(v.Item1, windows, StringComparison.OrdinalIgnoreCase)) { d.HasWindows = true; windowsFound = true; }
                }
            }
            return disks.Values.OrderBy(d => d.Number).ToList();
        }

        /// <summary>The drives LaunchOS may be written to. If it can't tell which disk Windows is on, none.</summary>
        public static List<Drive> List(bool showHardDrives, out string problem)
        {
            problem = "";
            var all = All(out bool windowsFound);
            if (!windowsFound)
            {
                problem = "Couldn't tell which drive Windows is on, so no drive is offered, to be safe.";
                return new List<Drive>();
            }
            var list = all.Where(d => Writable(d) && (showHardDrives || !d.IsHardDrive)).ToList();
            foreach (var d in list) ReadLaunchOS(d);
            return list;
        }

        /// <summary>A USB drive or memory card, without Windows, with 512-byte sectors (the only kind a PC starts LaunchOS from).</summary>
        public static bool Writable(Drive d) =>
            d.Size > 0 && !d.HasWindows && (d.Bus == BusUsb || d.Bus == BusSd || d.Bus == BusMmc);

        /// <summary>Every volume: (\\?\Volume{...}, disks it's on, drive letters, its name).</summary>
        static IEnumerable<Tuple<string, int[], List<string>, string>> AllVolumes()
        {
            var result = new List<Tuple<string, int[], List<string>, string>>();
            var name = new StringBuilder(1024);
            IntPtr find = Native.FindFirstVolume(name, name.Capacity);
            if (find == new IntPtr(-1)) return result;
            try
            {
                do
                {
                    string vol = name.ToString().TrimEnd('\\');
                    using (var vh = Native.CreateFile(vol, 0, Native.FILE_SHARE_READ | Native.FILE_SHARE_WRITE, IntPtr.Zero, Native.OPEN_EXISTING, 0, IntPtr.Zero))
                    {
                        if (vh.IsInvalid) continue;
                        result.Add(Tuple.Create(vol, Native.VolumeDisks(vh), Letters(name.ToString()), VolumeLabel(name.ToString())));
                    }
                } while (Native.FindNextVolume(find, name, name.Capacity));
            }
            finally { Native.FindVolumeClose(find); }
            return result;
        }

        /// <summary>The volumes on one disk, found again right now (just before writing).</summary>
        public static List<string> VolumesOn(int disk) =>
            AllVolumes().Where(v => v.Item2.Contains(disk)).Select(v => v.Item1).ToList();

        /// <summary>The disks the volume holding this file is on (to never write over the image being written).</summary>
        public static int[] DisksOfFile(string path)
        {
            try
            {
                var root = new StringBuilder(260);
                if (!Native.GetVolumePathName(Path.GetFullPath(path), root, root.Capacity)) return new int[0];
                var name = new StringBuilder(260);
                if (!Native.GetVolumeNameForVolumeMountPoint(root.ToString(), name, name.Capacity)) return new int[0];
                using (var vh = Native.CreateFile(name.ToString().TrimEnd('\\'), 0, Native.FILE_SHARE_READ | Native.FILE_SHARE_WRITE, IntPtr.Zero, Native.OPEN_EXISTING, 0, IntPtr.Zero))
                    return vh.IsInvalid ? new int[0] : Native.VolumeDisks(vh);
            }
            catch { return new int[0]; }
        }

        static List<string> Letters(string volume)
        {
            var buf = new char[1024];
            if (!Native.GetVolumePathNamesForVolumeName(volume, buf, buf.Length, out _)) return new List<string>();
            return new string(buf).Split(new[] { '\0' }, StringSplitOptions.RemoveEmptyEntries).ToList();
        }

        static string VolumeLabel(string volume)
        {
            try
            {
                var label = new StringBuilder(261); var fs = new StringBuilder(261);
                string root = volume.EndsWith("\\") ? volume : volume + "\\";
                return Native.GetVolumeInformation(root, label, label.Capacity, out _, out _, out _, fs, fs.Capacity) ? label.ToString().Trim() : "";
            }
            catch { return ""; }
        }

        /// <summary>Is there LaunchOS on this drive, and which version? (reads its first 64 KB)</summary>
        public static void ReadLaunchOS(Drive d)
        {
            using (var h = OpenDisk(d.Number, Native.GENERIC_READ))
            {
                if (h.IsInvalid) return;
                IntPtr buf = Native.VirtualAlloc(IntPtr.Zero, (UIntPtr)65536u, Native.MEM_COMMIT | Native.MEM_RESERVE, Native.PAGE_READWRITE);
                if (buf == IntPtr.Zero) return;
                try
                {
                    if (!Native.ReadFile(h, buf, 65536, out int got, IntPtr.Zero) || got < 65536) return;
                    var head = new byte[65536];
                    Marshal.Copy(buf, head, 0, head.Length);
                    d.HasLaunchOS = Images.ParseHeader(head, out d.LaunchOSVersion);
                }
                finally { Native.VirtualFree(buf, UIntPtr.Zero, Native.MEM_RELEASE); }
            }
        }

        /// <summary>The disk number a test VHD file is attached as (only for the automatic tests), or -1.</summary>
        public static int DiskOfVhd(string vhd)
        {
            var type = new Native.VIRTUAL_STORAGE_TYPE { DeviceId = 0, VendorId = Guid.Empty };   // any kind, found from the file
            const uint VIRTUAL_DISK_ACCESS_GET_INFO = 0x80000;
            int err = Native.OpenVirtualDisk(ref type, Path.GetFullPath(vhd), VIRTUAL_DISK_ACCESS_GET_INFO, 0, IntPtr.Zero, out SafeFileHandle h);
            if (err != 0) throw new IOException("Couldn't open the test disk " + vhd + " (error " + err + ")");
            using (h)
            {
                int size = 1024;
                var path = new StringBuilder(size / 2);
                err = Native.GetVirtualDiskPhysicalPath(h, ref size, path);
                if (err != 0) throw new IOException("The test disk isn't attached (error " + err + ")");
                string p = path.ToString();
                int at = p.IndexOf("PhysicalDrive", StringComparison.OrdinalIgnoreCase);
                return at >= 0 && int.TryParse(p.Substring(at + 13), out int n) ? n : -1;
            }
        }
    }
}
