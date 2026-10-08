// LaunchOS images: an ISO file, or LaunchOS.zip with the ISO inside. Also reads which LaunchOS
// version an image (or a USB drive written from one) holds, from its ISO 9660 header.
using System;
using System.IO;
using System.IO.Compression;
using System.Linq;
using System.Text;

namespace LaunchOSFlasher
{
    class ImageInfo
    {
        public string Path = "";
        public bool InZip;            // LaunchOS.iso inside LaunchOS.zip
        public long Length;
        public bool IsLaunchOS;
        public string Version = "";   // "" for LaunchOS older than 1.0 (which didn't record it)
        public string Name => System.IO.Path.GetFileName(Path);
    }

    static class Images
    {
        public const int PvdOffset = 32768;   // ISO 9660: the volume descriptor is in sector 16

        /// <summary>Is this a LaunchOS image, and which version? From the first 64 KB of an image or drive.</summary>
        public static bool ParseHeader(byte[] head, out string version)
        {
            version = "";
            if (head == null || head.Length < PvdOffset + 702) return false;
            if (head[PvdOffset] != 1 || Encoding.ASCII.GetString(head, PvdOffset + 1, 5) != "CD001") return false;
            string volume = Encoding.ASCII.GetString(head, PvdOffset + 40, 32).Trim();
            string app = Encoding.ASCII.GetString(head, PvdOffset + 574, 128).Trim();
            if (volume != "LAUNCHOS") return false;
            // LaunchOS 1.0 and later: application id "LAUNCHOS 1.0"
            if (app.StartsWith("LAUNCHOS "))
            {
                string v = app.Substring(9).Trim();
                if (v.Length > 0 && v.Length <= 12 && v.All(c => char.IsDigit(c) || c == '.')) version = v;
            }
            return true;
        }

        public static ImageInfo Inspect(string path)
        {
            var info = new ImageInfo { Path = path };
            byte[] head = new byte[65536];
            if (path.EndsWith(".zip", StringComparison.OrdinalIgnoreCase))
            {
                using (var zip = ZipFile.OpenRead(path))
                {
                    var e = IsoEntry(zip) ?? throw new InvalidDataException("There's no LaunchOS.iso in this zip file.");
                    info.InZip = true;
                    info.Length = e.Length;
                    using (var s = e.Open()) ReadFully(s, head);
                }
            }
            else
            {
                using (var s = File.OpenRead(path))
                {
                    info.Length = s.Length;
                    ReadFully(s, head);
                }
            }
            info.IsLaunchOS = ParseHeader(head, out info.Version);
            return info;
        }

        static ZipArchiveEntry IsoEntry(ZipArchive zip) =>
            zip.Entries.FirstOrDefault(x => x.Name.Equals("LaunchOS.iso", StringComparison.OrdinalIgnoreCase))
            ?? zip.Entries.FirstOrDefault(x => x.Name.EndsWith(".iso", StringComparison.OrdinalIgnoreCase));

        /// <summary>The image's bytes from the start. Dispose the returned object when done.</summary>
        public static Stream Open(ImageInfo info, out IDisposable owner)
        {
            if (info.InZip)
            {
                var zip = ZipFile.OpenRead(info.Path);
                owner = zip;
                return IsoEntry(zip).Open();
            }
            var fs = new FileStream(info.Path, FileMode.Open, FileAccess.Read, FileShare.Read, 1 << 20, FileOptions.SequentialScan);
            owner = fs;
            return fs;
        }

        public static int ReadFully(Stream s, byte[] buf, int offset = 0, int count = -1)
        {
            if (count < 0) count = buf.Length - offset;
            int got = 0;
            while (got < count)
            {
                int n = s.Read(buf, offset + got, count - got);
                if (n <= 0) break;
                got += n;
            }
            return got;
        }

        /// <summary>Compares versions like "0.9" and "1.0". An unknown version counts as older than any known one.</summary>
        public static int CompareVersions(string a, string b)
        {
            int[] pa = Parts(a), pb = Parts(b);
            for (int i = 0; i < Math.Max(pa.Length, pb.Length); i++)
            {
                int x = i < pa.Length ? pa[i] : 0, y = i < pb.Length ? pb[i] : 0;
                if (x != y) return x.CompareTo(y);
            }
            return 0;
        }

        static int[] Parts(string v) =>
            string.IsNullOrEmpty(v) ? new[] { -1 } : v.TrimStart('v', 'V').Split('.').Select(p => int.TryParse(p, out int n) ? n : 0).ToArray();

        public static string Describe(string version) => string.IsNullOrEmpty(version) ? "an older LaunchOS" : "LaunchOS " + version;

        public static string Size(long bytes) =>
            bytes >= 1L << 30 ? (bytes / (double)(1L << 30)).ToString("0.0") + " GB" : (bytes / (double)(1 << 20)).ToString("0") + " MB";
    }
}
