// The newest LaunchOS (and flasher) on GitHub, and downloading it.
using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using System.Net;
using System.Net.Http;
using System.Security.Cryptography;
using System.Threading;
using System.Threading.Tasks;
using System.Web.Script.Serialization;

namespace LaunchOSFlasher
{
    class Release
    {
        public string Version = "";      // "1.0"
        public string Page = "";         // the release's web page
        public string IsoUrl = "";       // LaunchOS.iso (or LaunchOS.zip, for releases that only have the zip)
        public bool IsZip;
        public long IsoSize;
        public string IsoSha256 = "";    // from SHA256SUMS.txt
        public string FlasherUrl = "";   // a newer flasher, if the release has one
    }

    static class Releases
    {
        public const string Repo = "maddoxdunlap1-glitch/LaunchOs";
        public static readonly string Downloads = System.IO.Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "LaunchOS Flasher");
        static readonly HttpClient Http = MakeClient();

        static HttpClient MakeClient()
        {
            ServicePointManager.SecurityProtocol |= SecurityProtocolType.Tls12;
            var h = new HttpClient { Timeout = TimeSpan.FromMinutes(5) };
            h.DefaultRequestHeaders.UserAgent.ParseAdd("LaunchOS-Flasher/" + Program.Version);
            return h;
        }

        /// <summary>The newest release, or null with the reason (offline, nothing published, private repository).</summary>
        public static async Task<Tuple<Release, string>> Latest()
        {
            try
            {
                var resp = await Http.GetAsync("https://api.github.com/repos/" + Repo + "/releases/latest");
                if (resp.StatusCode == HttpStatusCode.NotFound)
                    return Tuple.Create<Release, string>(null, "No LaunchOS release can be downloaded right now.");
                if (!resp.IsSuccessStatusCode)
                    return Tuple.Create<Release, string>(null, "GitHub didn't answer (" + (int)resp.StatusCode + "). Try again later.");
                string json = await resp.Content.ReadAsStringAsync();
                var r = Parse(json);
                if (r == null) return Tuple.Create<Release, string>(null, "The newest release has no LaunchOS.iso.");
                string sumsUrl = null;
                foreach (var a in Assets(json))
                    if (a.Key == "SHA256SUMS.txt") sumsUrl = a.Value;
                if (sumsUrl != null)
                {
                    foreach (var line in (await Http.GetStringAsync(sumsUrl)).Split('\n'))
                    {
                        var parts = line.Trim().Split(new[] { ' ', '*' }, StringSplitOptions.RemoveEmptyEntries);
                        if (parts.Length == 2 && parts[1] == (r.IsZip ? "LaunchOS.zip" : "LaunchOS.iso") && parts[0].Length == 64) r.IsoSha256 = parts[0].ToLowerInvariant();
                    }
                }
                return Tuple.Create(r, "");
            }
            catch (Exception)
            {
                return Tuple.Create<Release, string>(null, "Couldn't reach GitHub. Check your internet connection.");
            }
        }

        static IEnumerable<KeyValuePair<string, string>> Assets(string json)
        {
            var o = new JavaScriptSerializer().DeserializeObject(json) as Dictionary<string, object>;
            if (o == null || !(o.TryGetValue("assets", out object list) && list is IEnumerable)) yield break;
            foreach (var x in (IEnumerable)list)
                if (x is Dictionary<string, object> a && a.TryGetValue("name", out object n) && a.TryGetValue("browser_download_url", out object u))
                    yield return new KeyValuePair<string, string>((string)n, (string)u);
        }

        public static Release Parse(string json)
        {
            var o = new JavaScriptSerializer().DeserializeObject(json) as Dictionary<string, object>;
            if (o == null) return null;
            var r = new Release
            {
                Version = (o.TryGetValue("tag_name", out object t) ? t as string ?? "" : "").TrimStart('v', 'V'),
                Page = o.TryGetValue("html_url", out object p) ? p as string ?? "" : "",
            };
            if (o.TryGetValue("assets", out object list) && list is IEnumerable)
            {
                foreach (var x in (IEnumerable)list)
                {
                    if (!(x is Dictionary<string, object> a)) continue;
                    string name = a.TryGetValue("name", out object n) ? n as string : null;
                    string url = a.TryGetValue("browser_download_url", out object u) ? u as string : null;
                    long size = a.TryGetValue("size", out object s) ? Convert.ToInt64(s) : 0;
                    if (name == "LaunchOS.iso") { r.IsoUrl = url; r.IsoSize = size; r.IsZip = false; }
                    if (name == "LaunchOS.zip" && (r.IsoUrl == "" || r.IsZip)) { r.IsoUrl = url; r.IsoSize = size; r.IsZip = true; }
                    if (name == "LaunchOS-Flasher.exe") r.FlasherUrl = url;
                }
            }
            return string.IsNullOrEmpty(r.IsoUrl) ? null : r;
        }

        /// <summary>Downloads the release's ISO (or reuses an earlier download), checking its SHA-256.</summary>
        public static async Task<string> DownloadIso(Release r, IProgress<Tuple<long, long>> progress, CancellationToken ct)
        {
            Directory.CreateDirectory(Downloads);
            string dest = System.IO.Path.Combine(Downloads, "LaunchOS-" + r.Version + (r.IsZip ? ".zip" : ".iso"));
            if (File.Exists(dest) && new FileInfo(dest).Length == r.IsoSize && (r.IsoSha256 == "" || Sha256(dest, ct) == r.IsoSha256))
                return dest;
            string part = dest + ".part";
            using (var resp = await Http.GetAsync(r.IsoUrl, HttpCompletionOption.ResponseHeadersRead, ct))
            {
                resp.EnsureSuccessStatusCode();
                long total = resp.Content.Headers.ContentLength ?? r.IsoSize;
                using (var src = await resp.Content.ReadAsStreamAsync())
                using (var dst = new FileStream(part, FileMode.Create, FileAccess.Write, FileShare.None, 1 << 20))
                {
                    var buf = new byte[1 << 20];
                    long got = 0;
                    int n;
                    while ((n = await src.ReadAsync(buf, 0, buf.Length, ct)) > 0)
                    {
                        await dst.WriteAsync(buf, 0, n, ct);
                        got += n;
                        progress?.Report(Tuple.Create(got, total));
                    }
                }
            }
            if (r.IsoSha256 != "" && Sha256(part, ct) != r.IsoSha256)
            {
                File.Delete(part);
                throw new InvalidDataException("The download was damaged. Try again.");
            }
            if (File.Exists(dest)) File.Delete(dest);
            File.Move(part, dest);
            return dest;
        }

        public static string Sha256(string path, CancellationToken ct)
        {
            using (var sha = SHA256.Create())
            using (var s = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read, 1 << 20, FileOptions.SequentialScan))
            {
                var buf = new byte[1 << 20];
                int n;
                while ((n = s.Read(buf, 0, buf.Length)) > 0)
                {
                    ct.ThrowIfCancellationRequested();
                    sha.TransformBlock(buf, 0, n, null, 0);
                }
                sha.TransformFinalBlock(buf, 0, 0);
                return BitConverter.ToString(sha.Hash).Replace("-", "").ToLowerInvariant();
            }
        }
    }
}
