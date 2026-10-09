// Windows calls the flasher needs to read and write whole drives.
using System;
using System.ComponentModel;
using System.Runtime.InteropServices;
using System.Text;
using Microsoft.Win32.SafeHandles;

namespace LaunchOSFlasher
{
    static class Native
    {
        public const uint GENERIC_READ = 0x80000000, GENERIC_WRITE = 0x40000000;
        public const uint FILE_SHARE_READ = 1, FILE_SHARE_WRITE = 2;
        public const uint OPEN_EXISTING = 3;
        public const uint FILE_FLAG_NO_BUFFERING = 0x20000000, FILE_FLAG_WRITE_THROUGH = 0x80000000;

        public const uint FSCTL_LOCK_VOLUME = 0x00090018;
        public const uint FSCTL_DISMOUNT_VOLUME = 0x00090020;
        public const uint FSCTL_ALLOW_EXTENDED_DASD_IO = 0x00090083;
        public const uint IOCTL_DISK_GET_LENGTH_INFO = 0x0007405C;
        public const uint IOCTL_DISK_DELETE_DRIVE_LAYOUT = 0x0007C100;
        public const uint IOCTL_DISK_UPDATE_PROPERTIES = 0x00070140;
        public const uint IOCTL_DISK_GET_DRIVE_GEOMETRY_EX = 0x000700A0;
        public const uint IOCTL_DISK_CREATE_DISK = 0x0007C058;
        public const uint IOCTL_STORAGE_QUERY_PROPERTY = 0x002D1400;
        public const uint IOCTL_STORAGE_GET_DEVICE_NUMBER = 0x002D1080;
        public const uint IOCTL_VOLUME_GET_VOLUME_DISK_EXTENTS = 0x00560000;

        public const uint MEM_COMMIT = 0x1000, MEM_RESERVE = 0x2000, MEM_RELEASE = 0x8000, PAGE_READWRITE = 4;

        [DllImport("kernel32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
        public static extern SafeFileHandle CreateFile(string name, uint access, uint share, IntPtr security, uint creation, uint flags, IntPtr template);

        [DllImport("kernel32.dll", SetLastError = true)]
        public static extern bool DeviceIoControl(SafeFileHandle h, uint code, IntPtr inBuf, int inSize, IntPtr outBuf, int outSize, out int returned, IntPtr overlapped);

        [DllImport("kernel32.dll", SetLastError = true)]
        public static extern bool WriteFile(SafeFileHandle h, IntPtr buf, int count, out int written, IntPtr overlapped);

        [DllImport("kernel32.dll", SetLastError = true)]
        public static extern bool ReadFile(SafeFileHandle h, IntPtr buf, int count, out int read, IntPtr overlapped);

        [DllImport("kernel32.dll", SetLastError = true)]
        public static extern bool SetFilePointerEx(SafeFileHandle h, long distance, out long newPos, uint method);

        [DllImport("kernel32.dll", SetLastError = true)]
        public static extern bool FlushFileBuffers(SafeFileHandle h);

        [DllImport("kernel32.dll", SetLastError = true)]
        public static extern IntPtr VirtualAlloc(IntPtr addr, UIntPtr size, uint type, uint protect);

        [DllImport("kernel32.dll", SetLastError = true)]
        public static extern bool VirtualFree(IntPtr addr, UIntPtr size, uint type);

        [DllImport("kernel32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
        public static extern IntPtr FindFirstVolume(StringBuilder name, int len);

        [DllImport("kernel32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
        public static extern bool FindNextVolume(IntPtr find, StringBuilder name, int len);

        [DllImport("kernel32.dll", SetLastError = true)]
        public static extern bool FindVolumeClose(IntPtr find);

        [DllImport("kernel32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
        public static extern bool GetVolumePathNamesForVolumeName(string volume, char[] names, int len, out int needed);

        [DllImport("kernel32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
        public static extern bool GetVolumePathName(string path, StringBuilder volumePath, int len);

        [DllImport("kernel32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
        public static extern bool GetVolumeNameForVolumeMountPoint(string mountPoint, StringBuilder volumeName, int len);

        [DllImport("kernel32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
        public static extern bool GetVolumeInformation(string root, StringBuilder label, int labelLen, out uint serial, out uint maxName, out uint flags, StringBuilder fs, int fsLen);

        // virtual disks (only for the automatic tests: which disk a test VHD file is attached as)
        [StructLayout(LayoutKind.Sequential)]
        public struct VIRTUAL_STORAGE_TYPE { public uint DeviceId; public Guid VendorId; }

        [DllImport("virtdisk.dll", CharSet = CharSet.Unicode)]
        public static extern int OpenVirtualDisk(ref VIRTUAL_STORAGE_TYPE type, string path, uint access, uint flags, IntPtr parameters, out SafeFileHandle handle);

        [DllImport("virtdisk.dll", CharSet = CharSet.Unicode)]
        public static extern int GetVirtualDiskPhysicalPath(SafeFileHandle h, ref int sizeInBytes, StringBuilder path);

        [StructLayout(LayoutKind.Sequential)]
        public struct STORAGE_PROPERTY_QUERY { public int PropertyId; public int QueryType; public byte AdditionalParameters; }

        /// <summary>A Windows error with its own explanation ("Access is denied.") after what we were doing.</summary>
        public static Exception Error(string what)
        {
            int code = Marshal.GetLastWin32Error();
            string why = new Win32Exception(code).Message;
            return new Win32Exception(code, what + (string.IsNullOrEmpty(why) ? "" : ": " + why.TrimEnd('.') + "."));
        }

        public static void Ioctl(SafeFileHandle h, uint code, string what)
        {
            if (!DeviceIoControl(h, code, IntPtr.Zero, 0, IntPtr.Zero, 0, out _, IntPtr.Zero)) throw Error(what);
        }

        /// <summary>The disk's size and sector size. Works on a handle opened without any access rights.</summary>
        public static bool Geometry(SafeFileHandle h, out long size, out int sector)
        {
            size = 0; sector = 0;
            IntPtr buf = Marshal.AllocHGlobal(256);
            try
            {
                // DISK_GEOMETRY_EX: DISK_GEOMETRY { Cylinders(8) MediaType(4) TracksPerCylinder(4) SectorsPerTrack(4) BytesPerSector(4) }, DiskSize(8)
                if (!DeviceIoControl(h, IOCTL_DISK_GET_DRIVE_GEOMETRY_EX, IntPtr.Zero, 0, buf, 256, out int got, IntPtr.Zero) || got < 32) return false;
                sector = Marshal.ReadInt32(buf, 20);
                size = Marshal.ReadInt64(buf, 24);
                return size > 0 && sector > 0;
            }
            finally { Marshal.FreeHGlobal(buf); }
        }

        /// <summary>What the disk says about itself: bus (7 USB, 12 SD, 13 MMC, 11 SATA, 17 NVMe, 15 a VHD file...), removable, model, serial.</summary>
        public static bool Describe(SafeFileHandle h, out int bus, out bool removable, out string model, out string serial)
        {
            bus = -1; removable = false; model = ""; serial = "";
            var q = new STORAGE_PROPERTY_QUERY { PropertyId = 0, QueryType = 0 };
            int qs = Marshal.SizeOf(q);
            IntPtr qb = Marshal.AllocHGlobal(qs), ob = Marshal.AllocHGlobal(1024);
            try
            {
                Marshal.StructureToPtr(q, qb, false);
                if (!DeviceIoControl(h, IOCTL_STORAGE_QUERY_PROPERTY, qb, qs, ob, 1024, out int got, IntPtr.Zero) || got < 32) return false;
                // STORAGE_DEVICE_DESCRIPTOR: Version(4) Size(4) DeviceType(1) DeviceTypeModifier(1) RemovableMedia(1) CommandQueueing(1)
                //   VendorIdOffset(4)@12 ProductIdOffset(4)@16 ProductRevisionOffset(4)@20 SerialNumberOffset(4)@24 BusType(4)@28
                removable = Marshal.ReadByte(ob, 10) != 0;
                bus = Marshal.ReadInt32(ob, 28);
                int len = got;
                Func<int, string> Str = at => { int o = Marshal.ReadInt32(ob, at); return o > 0 && o < len ? (Marshal.PtrToStringAnsi(ob + o) ?? "").Trim() : ""; };
                string v = Str(12), p = Str(16);
                model = (v.Length > 0 && !p.StartsWith(v) ? v + " " + p : p).Trim();
                serial = Str(24);
                return true;
            }
            finally { Marshal.FreeHGlobal(qb); Marshal.FreeHGlobal(ob); }
        }

        /// <summary>The disk number of an open disk (to be sure it's still the one that was picked).</summary>
        public static int DeviceNumber(SafeFileHandle h)
        {
            IntPtr ob = Marshal.AllocHGlobal(12);
            try
            {
                // STORAGE_DEVICE_NUMBER: DeviceType(4) DeviceNumber(4) PartitionNumber(4)
                if (!DeviceIoControl(h, IOCTL_STORAGE_GET_DEVICE_NUMBER, IntPtr.Zero, 0, ob, 12, out _, IntPtr.Zero)) return -1;
                return Marshal.ReadInt32(ob, 4);
            }
            finally { Marshal.FreeHGlobal(ob); }
        }

        /// <summary>Which physical disks a volume sits on.</summary>
        public static int[] VolumeDisks(SafeFileHandle h)
        {
            IntPtr ob = Marshal.AllocHGlobal(4096);
            try
            {
                if (!DeviceIoControl(h, IOCTL_VOLUME_GET_VOLUME_DISK_EXTENTS, IntPtr.Zero, 0, ob, 4096, out _, IntPtr.Zero)) return new int[0];
                int n = Marshal.ReadInt32(ob);
                if (n < 0 || n > 160) return new int[0];
                var disks = new int[n];
                // VOLUME_DISK_EXTENTS: NumberOfDiskExtents(4) pad(4), then DISK_EXTENT { DiskNumber(4) pad(4) StartingOffset(8) ExtentLength(8) } = 24 bytes each
                for (int i = 0; i < n; i++) disks[i] = Marshal.ReadInt32(ob, 8 + i * 24);
                return disks;
            }
            finally { Marshal.FreeHGlobal(ob); }
        }

        /// <summary>Makes the disk an empty MBR disk (no partitions), so Windows sees it as blank.</summary>
        public static bool CreateEmptyMbr(SafeFileHandle h)
        {
            // CREATE_DISK: PartitionStyle(4) then CREATE_DISK_MBR { Signature(4) } in a 20-byte union (the GPT form is the largest)
            IntPtr b = Marshal.AllocHGlobal(24);
            try
            {
                for (int i = 0; i < 24; i += 4) Marshal.WriteInt32(b, i, 0);
                Marshal.WriteInt32(b, 4, new Random().Next(1, int.MaxValue));   // a disk signature
                return DeviceIoControl(h, IOCTL_DISK_CREATE_DISK, b, 24, IntPtr.Zero, 0, out _, IntPtr.Zero);
            }
            finally { Marshal.FreeHGlobal(b); }
        }
    }
}
