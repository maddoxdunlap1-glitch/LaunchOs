// Writes a LaunchOS image to a whole drive, byte for byte, then reads it back to check it.
//
// Before anything is written, the drive is checked again: it must still be the very drive that
// was picked (same disk number, model, serial number and size), still not hold Windows, and
// not hold the image being written. Then every volume on it is locked and taken offline (and
// kept locked), the old partition table is removed, the start of every old partition (and of
// the place LaunchOS keeps its saves) is cleared, so no old saves come back, and the image's
// first megabyte, where its partition table is, is written last, so Windows doesn't find and
// mount half-written partitions along the way. If writing fails or is stopped, the drive is
// left blank (an empty partition table) rather than half written.
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
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
        const int Align = 4096;         // buffers and lengths: a multiple of every drive's sector size

        /// <summary>(what's happening, bytes done, bytes in this step)</summary>
        public Action<string, long, long> Progress = (s, d, t) => { };

        /// <summary>Whether anything was written to the drive (then a failure leaves it blank).</summary>
        public bool Touched { get; private set; }

        public void Write(Drive drive, ImageInfo image, bool verify, CancellationToken ct, bool testDisk = false)
        {
            Progress("Getting the drive ready", 0, 1);
            // the image must not be on the drive that's about to be erased
            if (Drives.DisksOfFile(image.Path).Contains(drive.Number))
                throw new IOException(image.Name + " is on that USB drive. Copy it to your PC first (for example to Downloads), then pick it from there.");
            // still the same drive, and still no Windows on it (things may have been plugged in or out meanwhile)
            var now = Drives.All(out bool windowsFound).FirstOrDefault(d => d.Number == drive.Number);
            if (now == null || now.Identity != drive.Identity)
                throw new IOException("The USB drive changed since you picked it. Pick it again.");
            if (!testDisk && (!windowsFound || now.HasWindows || !Drives.Writable(now)))
                throw new IOException("That drive can't be written to. Pick a USB drive.");
            if (now.SectorSize != 512)
                throw new IOException("This drive uses " + now.SectorSize + "-byte sectors, and PCs can't start LaunchOS from those. Use another USB drive.");

            var locks = new List<SafeFileHandle>();
            IntPtr buf = Native.VirtualAlloc(IntPtr.Zero, (UIntPtr)(uint)Chunk, Native.MEM_COMMIT | Native.MEM_RESERVE, Native.PAGE_READWRITE);
            if (buf == IntPtr.Zero) throw Native.Error("Not enough memory");
            var src = Images.Open(image, out IDisposable owner);   // (opened before the drive is touched)
            SafeFileHandle disk = null;
            try
            {
                foreach (var vol in Drives.VolumesOn(drive.Number)) locks.Add(LockVolume(vol));
                disk = Native.CreateFile(@"\\.\PhysicalDrive" + drive.Number, Native.GENERIC_READ | Native.GENERIC_WRITE,
                    Native.FILE_SHARE_READ | Native.FILE_SHARE_WRITE, IntPtr.Zero, Native.OPEN_EXISTING,
                    Native.FILE_FLAG_NO_BUFFERING | Native.FILE_FLAG_WRITE_THROUGH, IntPtr.Zero);
                if (disk.IsInvalid) throw Native.Error("Couldn't open the drive");
                // the handle really is that drive
                if (Native.DeviceNumber(disk) != drive.Number || Drives.IdentityOf(disk) != drive.Identity)
                    throw new IOException("The USB drive changed since you picked it. Pick it again.");
                Native.DeviceIoControl(disk, Native.FSCTL_ALLOW_EXTENDED_DASD_IO, IntPtr.Zero, 0, IntPtr.Zero, 0, out _, IntPtr.Zero);
                long size = drive.Size;
                long padded = (image.Length + Align - 1) / Align * Align;
                if (padded > size) throw new IOException("This drive is too small for LaunchOS: it needs " + Images.Size(image.Length) + ".");

                // where old partitions start (to clear them: an old save area must not come back)
                var starts = OldPartitionStarts(disk, buf);
                Touched = true;
                Native.DeviceIoControl(disk, Native.IOCTL_DISK_DELETE_DRIVE_LAYOUT, IntPtr.Zero, 0, IntPtr.Zero, 0, out _, IntPtr.Zero);
                Zero(buf, Chunk);
                WriteAt(disk, 0, buf, Head);                                   // the old partition table
                if (size >= 2 * Head) WriteAt(disk, size - Head, buf, Head);   // and the old backup one at the end
                // LaunchOS makes its save area right after itself (rounded to a megabyte)
                long saves = (image.Length + Head - 1) / Head * Head;
                foreach (long at in starts.Concat(new[] { saves }).Distinct())
                    if (at >= Head && at + Head <= size) WriteAt(disk, at, buf, Head);

                byte[] head = new byte[Head];
                byte[] managed = new byte[Chunk];
                string sum;
                using (var sha = SHA256.Create())
                {
                    int h = Images.ReadFully(src, head, 0, (int)Math.Min(Head, image.Length));
                    sha.TransformBlock(head, 0, h, null, 0);
                    long pos = Head;
                    while (pos < image.Length)
                    {
                        ct.ThrowIfCancellationRequested();
                        int want = (int)Math.Min(Chunk, image.Length - pos);
                        int got = Images.ReadFully(src, managed, 0, want);
                        if (got != want) throw new EndOfStreamException("The LaunchOS file ended early. Download it again.");
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
                // the first megabyte last: now the drive has its new partitions
                ct.ThrowIfCancellationRequested();
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
                Progress("Done", 1, 1);
            }
            catch
            {
                // stopped or failed halfway: a blank drive (Windows offers to format it) beats a broken one
                if (Touched && disk != null && !disk.IsInvalid)
                {
                    try
                    {
                        Zero(buf, Head);
                        WriteAt(disk, 0, buf, Head);
                        Native.CreateEmptyMbr(disk);
                        Native.DeviceIoControl(disk, Native.IOCTL_DISK_UPDATE_PROPERTIES, IntPtr.Zero, 0, IntPtr.Zero, 0, out _, IntPtr.Zero);
                    }
                    catch { /* the drive may be gone */ }
                }
                throw;
            }
            finally
            {
                owner.Dispose();
                disk?.Dispose();
                foreach (var h in locks) h.Dispose();   // unlocks the volumes
                Native.VirtualFree(buf, UIntPtr.Zero, Native.MEM_RELEASE);
            }
        }

        /// <summary>Where the partitions in the drive's old MBR start (bytes).</summary>
        static List<long> OldPartitionStarts(SafeFileHandle disk, IntPtr buf)
        {
            var starts = new List<long>();
            try
            {
                ReadAt(disk, 0, buf, Align);
                var mbr = new byte[512];
                Marshal.Copy(buf, mbr, 0, 512);
                if (mbr[510] != 0x55 || mbr[511] != 0xAA) return starts;
                for (int i = 0; i < 4; i++)
                {
                    int e = 446 + 16 * i;
                    if (mbr[e + 4] == 0 || mbr[e + 4] == 0xEE) continue;   // empty, or a GPT disk's guard
                    long lba = BitConverter.ToUInt32(mbr, e + 8);
                    if (lba > 0) starts.Add(lba * 512);
                }
            }
            catch { /* unreadable: nothing extra to clear */ }
            return starts;
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
