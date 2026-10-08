// Writes a LaunchOS image to a whole drive, byte for byte, then reads it back to check it.
//
// Windows must not touch the drive while it's written, so: every volume on it is locked and
// taken offline first (and kept locked), the old partition table is removed, and the image's
// first megabyte (where its partition table is) is written last, so Windows doesn't find and
// mount half-written partitions along the way.
using System;
using System.Collections.Generic;
using System.IO;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Threading;
using Microsoft.Win32.SafeHandles;

namespace LaunchOSFlasher
{
    class Writer
    {
        const int Head = 1 << 20;       // written last
        const int Chunk = 4 << 20;
        const int Align = 4096;         // a multiple of every drive's sector size

        /// <summary>(what's happening, bytes done, bytes in this step)</summary>
        public Action<string, long, long> Progress = (s, d, t) => { };

        public void Write(Drive drive, ImageInfo image, bool verify, CancellationToken ct)
        {
            var locks = new List<SafeFileHandle>();
            IntPtr buf = Native.VirtualAlloc(IntPtr.Zero, (UIntPtr)(uint)Chunk, Native.MEM_COMMIT | Native.MEM_RESERVE, Native.PAGE_READWRITE);
            if (buf == IntPtr.Zero) throw Native.Error("Not enough memory");
            try
            {
                Progress("Getting the drive ready", 0, 1);
                foreach (var vol in drive.Volumes) locks.Add(LockVolume(vol));
                using (var disk = Native.CreateFile(@"\\.\PhysicalDrive" + drive.Number, Native.GENERIC_READ | Native.GENERIC_WRITE,
                    Native.FILE_SHARE_READ | Native.FILE_SHARE_WRITE, IntPtr.Zero, Native.OPEN_EXISTING,
                    Native.FILE_FLAG_NO_BUFFERING | Native.FILE_FLAG_WRITE_THROUGH, IntPtr.Zero))
                {
                    if (disk.IsInvalid) throw Native.Error("Couldn't open the drive");
                    Native.DeviceIoControl(disk, Native.FSCTL_ALLOW_EXTENDED_DASD_IO, IntPtr.Zero, 0, IntPtr.Zero, 0, out _, IntPtr.Zero);
                    long size = Native.DiskLength(disk);
                    long padded = (image.Length + Align - 1) / Align * Align;
                    if (padded > size) throw new IOException("This drive is too small for LaunchOS: it needs " + Images.Size(image.Length) + ".");
                    Native.DeviceIoControl(disk, Native.IOCTL_DISK_DELETE_DRIVE_LAYOUT, IntPtr.Zero, 0, IntPtr.Zero, 0, out _, IntPtr.Zero);
                    // clear the start and the end (an old backup partition table lives at the end)
                    Zero(buf, Chunk);
                    WriteAt(disk, 0, buf, Head);
                    if (size >= 2 * Head) WriteAt(disk, size / Align * Align - Head, buf, Head);

                    byte[] head = new byte[Head];
                    byte[] managed = new byte[Chunk];
                    string sum;
                    using (var sha = SHA256.Create())
                    {
                        var src = Images.Open(image, out IDisposable owner);
                        try
                        {
                            int h = Images.ReadFully(src, head);
                            sha.TransformBlock(head, 0, h, null, 0);
                            long pos = Head;
                            while (pos < image.Length)
                            {
                                ct.ThrowIfCancellationRequested();
                                int want = (int)Math.Min(Chunk, image.Length - pos);
                                int got = Images.ReadFully(src, managed, 0, want);
                                if (got != want) throw new EndOfStreamException("The image ended early. Download it again.");
                                sha.TransformBlock(managed, 0, got, null, 0);
                                int len = (got + Align - 1) / Align * Align;
                                if (len > got) Array.Clear(managed, got, len - got);
                                Marshal.Copy(managed, 0, buf, len);
                                WriteAt(disk, pos, buf, len);
                                pos += got;
                                Progress("Writing LaunchOS", pos, image.Length);
                            }
                            sha.TransformFinalBlock(managed, 0, 0);
                            sum = Hex(sha.Hash);
                        }
                        finally { owner.Dispose(); }
                    }
                    // the first megabyte last: now the drive has its new partitions
                    Zero(buf, Head);
                    Marshal.Copy(head, 0, buf, (int)Math.Min(Head, image.Length));
                    WriteAt(disk, 0, buf, Head);
                    Native.FlushFileBuffers(disk);

                    if (verify)
                    {
                        using (var sha = SHA256.Create())
                        {
                            long pos = 0;
                            while (pos < image.Length)
                            {
                                ct.ThrowIfCancellationRequested();
                                int want = (int)Math.Min(Chunk, image.Length - pos);
                                int len = (want + Align - 1) / Align * Align;
                                ReadAt(disk, pos, buf, len);
                                Marshal.Copy(buf, managed, 0, want);
                                sha.TransformBlock(managed, 0, want, null, 0);
                                pos += want;
                                Progress("Checking what was written", pos, image.Length);
                            }
                            sha.TransformFinalBlock(managed, 0, 0);
                            if (Hex(sha.Hash) != sum) throw new IOException("What was written doesn't match LaunchOS. The drive may be failing: try another one.");
                        }
                    }
                    Native.DeviceIoControl(disk, Native.IOCTL_DISK_UPDATE_PROPERTIES, IntPtr.Zero, 0, IntPtr.Zero, 0, out _, IntPtr.Zero);
                }
                Progress("Done", 1, 1);
            }
            finally
            {
                foreach (var h in locks) h.Dispose();   // unlocks the volumes
                Native.VirtualFree(buf, UIntPtr.Zero, Native.MEM_RELEASE);
            }
        }

        static SafeFileHandle LockVolume(string volume)
        {
            var h = Native.CreateFile(volume, Native.GENERIC_READ | Native.GENERIC_WRITE, Native.FILE_SHARE_READ | Native.FILE_SHARE_WRITE,
                IntPtr.Zero, Native.OPEN_EXISTING, 0, IntPtr.Zero);
            if (h.IsInvalid) throw Native.Error("Couldn't open a part of the drive");
            for (int i = 0; ; i++)
            {
                if (Native.DeviceIoControl(h, Native.FSCTL_LOCK_VOLUME, IntPtr.Zero, 0, IntPtr.Zero, 0, out _, IntPtr.Zero)) break;
                if (i >= 40) { h.Dispose(); throw new IOException("The drive is in use. Close any windows or programs using it, then try again."); }
                Thread.Sleep(250);
            }
            Native.DeviceIoControl(h, Native.FSCTL_DISMOUNT_VOLUME, IntPtr.Zero, 0, IntPtr.Zero, 0, out _, IntPtr.Zero);
            return h;
        }

        static void WriteAt(SafeFileHandle h, long pos, IntPtr buf, int len)
        {
            if (!Native.SetFilePointerEx(h, pos, out _, 0)) throw Native.Error("Couldn't write to the drive");
            if (!Native.WriteFile(h, buf, len, out int done, IntPtr.Zero) || done != len) throw Native.Error("Couldn't write to the drive. Was it unplugged?");
        }

        static void ReadAt(SafeFileHandle h, long pos, IntPtr buf, int len)
        {
            if (!Native.SetFilePointerEx(h, pos, out _, 0)) throw Native.Error("Couldn't read the drive");
            if (!Native.ReadFile(h, buf, len, out int done, IntPtr.Zero) || done != len) throw Native.Error("Couldn't read the drive. Was it unplugged?");
        }

        static void Zero(IntPtr buf, int len)
        {
            var z = new byte[65536];
            for (int off = 0; off < len; off += z.Length) Marshal.Copy(z, 0, buf + off, Math.Min(z.Length, len - off));
        }

        static string Hex(byte[] b) => BitConverter.ToString(b).Replace("-", "").ToLowerInvariant();
    }
}
