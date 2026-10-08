// Windows calls the flasher needs to read and write whole drives.
using System;
using System.ComponentModel;
using System.Runtime.InteropServices;
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
        public static extern IntPtr FindFirstVolume(System.Text.StringBuilder name, int len);

        [DllImport("kernel32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
        public static extern bool FindNextVolume(IntPtr find, System.Text.StringBuilder name, int len);

        [DllImport("kernel32.dll", SetLastError = true)]
        public static extern bool FindVolumeClose(IntPtr find);

        [DllImport("kernel32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
        public static extern bool GetVolumePathNamesForVolumeName(string volume, char[] names, int len, out int needed);

        [StructLayout(LayoutKind.Sequential)]
        public struct STORAGE_PROPERTY_QUERY { public int PropertyId; public int QueryType; public byte AdditionalParameters; }

        [StructLayout(LayoutKind.Sequential)]
        public struct STORAGE_DEVICE_NUMBER { public int DeviceType; public int DeviceNumber; public int PartitionNumber; }

        public static Win32Exception Error(string what) => new Win32Exception(Marshal.GetLastWin32Error(), what);

        public static void Ioctl(SafeFileHandle h, uint code, string what)
        {
            if (!DeviceIoControl(h, code, IntPtr.Zero, 0, IntPtr.Zero, 0, out _, IntPtr.Zero)) throw Error(what);
        }

        public static long DiskLength(SafeFileHandle h)
        {
            IntPtr buf = Marshal.AllocHGlobal(8);
            try
            {
                if (!DeviceIoControl(h, IOCTL_DISK_GET_LENGTH_INFO, IntPtr.Zero, 0, buf, 8, out _, IntPtr.Zero)) throw Error("Couldn't read the drive's size");
                return Marshal.ReadInt64(buf);
            }
            finally { Marshal.FreeHGlobal(buf); }
        }

        /// <summary>The disk's bus: 7 USB, 12 SD, 13 MMC, 11 SATA, 17 NVMe, 15 virtual file-backed (VHD)…</summary>
        public static int BusType(SafeFileHandle h, out bool removable)
        {
            removable = false;
            var q = new STORAGE_PROPERTY_QUERY { PropertyId = 0, QueryType = 0 };
            int qs = Marshal.SizeOf(q);
            IntPtr qb = Marshal.AllocHGlobal(qs), ob = Marshal.AllocHGlobal(1024);
            try
            {
                Marshal.StructureToPtr(q, qb, false);
                if (!DeviceIoControl(h, IOCTL_STORAGE_QUERY_PROPERTY, qb, qs, ob, 1024, out _, IntPtr.Zero)) return -1;
                // STORAGE_DEVICE_DESCRIPTOR: Version(4) Size(4) DeviceType(1) DeviceTypeModifier(1) RemovableMedia(1) CommandQueueing(1) ... BusType at 28
                removable = Marshal.ReadByte(ob, 10) != 0;
                return Marshal.ReadInt32(ob, 28);
            }
            finally { Marshal.FreeHGlobal(qb); Marshal.FreeHGlobal(ob); }
        }

        /// <summary>Which physical disks a volume sits on.</summary>
        public static int[] VolumeDisks(SafeFileHandle h)
        {
            IntPtr ob = Marshal.AllocHGlobal(4096);
            try
            {
                if (!DeviceIoControl(h, IOCTL_VOLUME_GET_VOLUME_DISK_EXTENTS, IntPtr.Zero, 0, ob, 4096, out _, IntPtr.Zero)) return new int[0];
                int n = Marshal.ReadInt32(ob);
                var disks = new int[n];
                // VOLUME_DISK_EXTENTS: NumberOfDiskExtents(4) pad(4), then DISK_EXTENT { DiskNumber(4) pad(4) StartingOffset(8) ExtentLength(8) } = 24 bytes each
                for (int i = 0; i < n; i++) disks[i] = Marshal.ReadInt32(ob, 8 + i * 24);
                return disks;
            }
            finally { Marshal.FreeHGlobal(ob); }
        }
    }
}
