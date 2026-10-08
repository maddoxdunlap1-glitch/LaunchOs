// The drives LaunchOS can be written to: USB drives and memory cards only, never the drive
// Windows runs from, never a drive inside the PC.
using System;
using System.Collections.Generic;
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
        public long Size;
        public int Bus;                     // 7 USB, 12 SD, 13 MMC
        public bool Removable;
        public bool HasWindows;             // Windows (or the page file) is on it
        public List<string> Letters = new List<string>();
        public List<string> Volumes = new List<string>();   // \\?\Volume{...} names
        public bool HasLaunchOS;
        public string LaunchOSVersion = "";

        public string Label
        {
            get
            {
                string letters = Letters.Count > 0 ? " (" + string.Join(", ", Letters.Select(l => l.TrimEnd('\\'))) + ")" : "";
                return (Model.Length > 0 ? Model : "Drive " + Number) + " · " + Images.Size(Size) + letters;
            }
        }
    }

    static class Drives
    {
        public const int BusUsb = 7, BusSd = 12, BusMmc = 13;

        /// <summary>Every disk Windows sees. allowAny: also drives inside the PC (only for the automatic tests).</summary>
        public static List<Drive> List(bool allowAny = false)
        {
            var disks = new Dictionary<int, Drive>();
            for (int i = 0; i < 64; i++)
            {
                using (var h = Native.CreateFile(@"\\.\PhysicalDrive" + i, 0, Native.FILE_SHARE_READ | Native.FILE_SHARE_WRITE, IntPtr.Zero, Native.OPEN_EXISTING, 0, IntPtr.Zero))
                {
                    if (h.IsInvalid) continue;
                    var d = new Drive { Number = i };
                    d.Bus = Native.BusType(h, out d.Removable);
                    d.Model = Model(h);
                    try { d.Size = Native.DiskLength(h); } catch { continue; }
                    disks[i] = d;
                }
            }
            // volumes (and their letters) on each disk
            string windows = Environment.GetEnvironmentVariable("SystemDrive") ?? "C:";
            var name = new StringBuilder(1024);
            IntPtr find = Native.FindFirstVolume(name, name.Capacity);
            if (find != new IntPtr(-1))
            {
                do
                {
                    string vol = name.ToString().TrimEnd('\\');
                    using (var vh = Native.CreateFile(vol, 0, Native.FILE_SHARE_READ | Native.FILE_SHARE_WRITE, IntPtr.Zero, Native.OPEN_EXISTING, 0, IntPtr.Zero))
                    {
                        if (vh.IsInvalid) continue;
                        var letters = Letters(name.ToString());
                        foreach (int disk in Native.VolumeDisks(vh))
                        {
                            if (!disks.TryGetValue(disk, out Drive d)) continue;
                            d.Volumes.Add(vol);
                            d.Letters.AddRange(letters);
                            if (letters.Any(l => l.StartsWith(windows, StringComparison.OrdinalIgnoreCase))) d.HasWindows = true;
                        }
                    }
                } while (Native.FindNextVolume(find, name, name.Capacity));
                Native.FindVolumeClose(find);
            }
            var list = disks.Values.Where(d => d.Size > 0 && !d.HasWindows &&
                (allowAny || d.Bus == BusUsb || d.Bus == BusSd || d.Bus == BusMmc)).OrderBy(d => d.Number).ToList();
            foreach (var d in list) ReadLaunchOS(d);
            return list;
        }

        static string Model(SafeFileHandle h)
        {
            var q = new Native.STORAGE_PROPERTY_QUERY();
            int qs = Marshal.SizeOf(q);
            IntPtr qb = Marshal.AllocHGlobal(qs), ob = Marshal.AllocHGlobal(1024);
            try
            {
                Marshal.StructureToPtr(q, qb, false);
                if (!Native.DeviceIoControl(h, Native.IOCTL_STORAGE_QUERY_PROPERTY, qb, qs, ob, 1024, out _, IntPtr.Zero)) return "";
                int vendor = Marshal.ReadInt32(ob, 12), product = Marshal.ReadInt32(ob, 16);
                string v = vendor > 0 && vendor < 1024 ? Marshal.PtrToStringAnsi(ob + vendor).Trim() : "";
                string p = product > 0 && product < 1024 ? Marshal.PtrToStringAnsi(ob + product).Trim() : "";
                return (v.Length > 0 && !p.StartsWith(v) ? v + " " + p : p).Trim();
            }
            finally { Marshal.FreeHGlobal(qb); Marshal.FreeHGlobal(ob); }
        }

        static List<string> Letters(string volume)
        {
            var buf = new char[1024];
            if (!Native.GetVolumePathNamesForVolumeName(volume, buf, buf.Length, out _)) return new List<string>();
            return new string(buf).Split(new[] { '\0' }, StringSplitOptions.RemoveEmptyEntries).ToList();
        }

        /// <summary>Is there LaunchOS on this drive, and which version? (reads its first 64 KB)</summary>
        public static void ReadLaunchOS(Drive d)
        {
            using (var h = Native.CreateFile(@"\\.\PhysicalDrive" + d.Number, Native.GENERIC_READ, Native.FILE_SHARE_READ | Native.FILE_SHARE_WRITE, IntPtr.Zero, Native.OPEN_EXISTING, 0, IntPtr.Zero))
            {
                if (h.IsInvalid) return;
                IntPtr buf = Marshal.AllocHGlobal(65536);
                try
                {
                    if (!Native.ReadFile(h, buf, 65536, out int got, IntPtr.Zero) || got < 65536) return;
                    var head = new byte[65536];
                    Marshal.Copy(buf, head, 0, head.Length);
                    d.HasLaunchOS = Images.ParseHeader(head, out d.LaunchOSVersion);
                }
                finally { Marshal.FreeHGlobal(buf); }
            }
        }
    }
}
