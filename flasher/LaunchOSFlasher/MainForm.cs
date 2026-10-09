// The LaunchOS Flasher window: pick LaunchOS (the newest, or a file), pick a USB drive, write.
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using System.Windows.Forms;

namespace LaunchOSFlasher
{
    class MainForm : Form
    {
        static readonly Color Bg = Color.FromArgb(11, 23, 38), Card = Color.FromArgb(18, 34, 53), Line = Color.FromArgb(34, 52, 74),
            Ink = Color.FromArgb(242, 244, 243), Ink2 = Color.FromArgb(185, 198, 211), Mute = Color.FromArgb(138, 152, 168),
            Accent = Color.FromArgb(61, 220, 107), AccentInk = Color.FromArgb(11, 23, 38), Warn = Color.FromArgb(230, 199, 90), Bad = Color.FromArgb(255, 122, 116);

        Release latest;
        string latestError = "";
        ImageInfo file;
        bool busy, asking, refreshing, closeWhenDone;
        CancellationTokenSource cts;

        readonly Label status = new Label(), fileLabel = new Label(), note = new Label(), driveNote = new Label(), work = new Label(), banner = new Label(), foot = new Label();
        readonly RadioButton useNewest = new RadioButton(), useFile = new RadioButton();
        readonly Button browse = new Button(), write = new Button(), cancel = new Button(), refresh = new Button();
        readonly CheckBox showHard = new CheckBox();
        readonly ComboBox drives = new ComboBox();
        readonly Meter meter = new Meter();
        readonly System.Windows.Forms.Timer deviceTimer = new System.Windows.Forms.Timer { Interval = 900 };

        public MainForm()
        {
            SuspendLayout();
            AutoScaleDimensions = new SizeF(96f, 96f);
            AutoScaleMode = AutoScaleMode.Dpi;
            Text = "LaunchOS Flasher";
            Icon = Icon.ExtractAssociatedIcon(Application.ExecutablePath);
            BackColor = Bg; ForeColor = Ink;
            Font = new Font("Segoe UI", 10f);
            FormBorderStyle = FormBorderStyle.FixedSingle; MaximizeBox = false;
            ClientSize = new Size(760, 616);
            StartPosition = FormStartPosition.CenterScreen;
            DoubleBuffered = true;

            var logo = new PictureBox { Image = Icon.ToBitmap(), SizeMode = PictureBoxSizeMode.Zoom, Bounds = new Rectangle(28, 22, 52, 52) };
            try { logo.Image = new Icon(Icon, 64, 64).ToBitmap(); } catch { }
            var title = new Label { Text = "LaunchOS Flasher", Font = new Font("Segoe UI Semibold", 18f), AutoSize = true, Location = new Point(92, 20) };
            var sub = new Label { Text = "Puts LaunchOS on a USB drive, ready to start a PC from.", ForeColor = Ink2, AutoSize = true, Location = new Point(95, 54) };
            banner.Bounds = new Rectangle(28, 88, 704, 34); banner.BackColor = Color.FromArgb(58, 50, 18); banner.ForeColor = Warn;
            banner.TextAlign = ContentAlignment.MiddleLeft; banner.Padding = new Padding(10, 0, 0, 0); banner.Visible = false; banner.Cursor = Cursors.Hand;
            banner.Click += (s, e) => OpenPage(latest != null && latest.Page != "" ? latest.Page : "");

            var card1 = CardPanel(28, 130, 704, 176, "1", "LaunchOS");
            status.Bounds = new Rectangle(58, 44, 630, 22); status.ForeColor = Ink2; status.AutoEllipsis = true; status.Text = "Looking for the newest LaunchOS…";
            Radio(useNewest, "Download the newest LaunchOS", 58, 72);
            Radio(useFile, "Use a file on this PC (LaunchOS.iso or LaunchOS.zip)", 58, 102);
            Style(browse, "Choose…", false); browse.Bounds = new Rectangle(570, 98, 110, 32);
            fileLabel.Bounds = new Rectangle(80, 130, 600, 20); fileLabel.ForeColor = Mute; fileLabel.AutoEllipsis = true;
            note.Bounds = new Rectangle(58, 150, 630, 22); note.ForeColor = Warn; note.AutoEllipsis = true;
            card1.Controls.AddRange(new Control[] { status, useNewest, useFile, browse, fileLabel, note });

            var card2 = CardPanel(28, 318, 704, 150, "2", "USB drive");
            drives.Bounds = new Rectangle(58, 46, 500, 30); drives.DropDownStyle = ComboBoxStyle.DropDownList; drives.FlatStyle = FlatStyle.Flat;
            drives.BackColor = Bg; drives.ForeColor = Ink; drives.DrawMode = DrawMode.OwnerDrawFixed; drives.ItemHeight = 24;
            drives.DrawItem += DrawDrive;
            Style(refresh, "Look again", false); refresh.Bounds = new Rectangle(570, 45, 110, 32);
            driveNote.Bounds = new Rectangle(58, 84, 630, 38); driveNote.ForeColor = Ink2;
            showHard.Text = "Also show USB hard drives (they're hidden so a backup drive isn't erased by mistake)";
            showHard.AutoSize = true; showHard.Location = new Point(58, 122); showHard.ForeColor = Mute; showHard.BackColor = Card; showHard.FlatStyle = FlatStyle.Flat;
            card2.Controls.AddRange(new Control[] { drives, refresh, driveNote, showHard });

            meter.Bounds = new Rectangle(28, 490, 704, 10); meter.Visible = false;
            work.Bounds = new Rectangle(28, 506, 470, 64); work.ForeColor = Ink2;
            Style(write, "Write LaunchOS", true); write.Bounds = new Rectangle(512, 510, 220, 46);
            Style(cancel, "Stop", false); cancel.Bounds = new Rectangle(386, 510, 116, 46); cancel.Visible = false;
            foot.Bounds = new Rectangle(28, 584, 704, 22); foot.ForeColor = Mute; foot.AutoEllipsis = true;
            foot.Text = "Flasher " + Program.Version + " · Only downloads LaunchOS that checks out against its published checksum.";

            Controls.AddRange(new Control[] { logo, title, sub, banner, card1, card2, meter, work, write, cancel, foot });

            useFile.Checked = true;   // (until the newest is known; set before the handlers, so no file dialog opens)
            useNewest.CheckedChanged += (s, e) => UpdateState();
            useFile.CheckedChanged += (s, e) => { if (useFile.Checked && file == null && !asking) Browse(); UpdateState(); };
            browse.Click += (s, e) => Browse();
            refresh.Click += async (s, e) => await RefreshDrives();
            showHard.CheckedChanged += async (s, e) => await RefreshDrives();
            drives.SelectedIndexChanged += (s, e) => UpdateState();
            write.Click += async (s, e) => { if (drives.SelectedItem is Drive d) await Go(d, false); };
            cancel.Click += (s, e) => cts?.Cancel();
            deviceTimer.Tick += async (s, e) => { deviceTimer.Stop(); if (!busy && !asking) await RefreshDrives(true); };
            Shown += async (s, e) => { await RefreshDrives(); await CheckLatest(); };
            FormClosing += OnClosing;
            ResumeLayout(false);
            PerformLayout();
            UpdateState();
        }

        // ---------- look ----------

        Panel CardPanel(int x, int y, int w, int h, string num, string name)
        {
            var p = new RoundPanel { Bounds = new Rectangle(x, y, w, h), BackColor = Card, Border = Line };
            p.Controls.Add(new Label { Text = num, Font = new Font("Segoe UI Semibold", 11f), ForeColor = AccentInk, BackColor = Accent, TextAlign = ContentAlignment.MiddleCenter, Bounds = new Rectangle(18, 14, 26, 26) });
            p.Controls.Add(new Label { Text = name, Font = new Font("Segoe UI Semibold", 13f), AutoSize = true, Location = new Point(54, 13), BackColor = Card });
            return p;
        }

        void Radio(RadioButton r, string text, int x, int y)
        {
            r.Text = text; r.AutoSize = true; r.Location = new Point(x, y); r.ForeColor = Ink; r.BackColor = Card; r.FlatStyle = FlatStyle.Flat;
        }

        static void Style(Button b, string text, bool primary)
        {
            b.Text = text; b.FlatStyle = FlatStyle.Flat; b.FlatAppearance.BorderSize = primary ? 0 : 1; b.FlatAppearance.BorderColor = Line;
            b.BackColor = primary ? Accent : Card; b.ForeColor = primary ? AccentInk : Ink; b.Cursor = Cursors.Hand;
            b.Font = new Font("Segoe UI Semibold", primary ? 12f : 10f);
            b.FlatAppearance.MouseOverBackColor = primary ? Color.FromArgb(94, 232, 136) : Color.FromArgb(26, 43, 64);
        }

        void DrawDrive(object sender, DrawItemEventArgs e)
        {
            e.Graphics.FillRectangle(new SolidBrush((e.State & DrawItemState.Selected) != 0 && (e.State & DrawItemState.ComboBoxEdit) == 0 ? Line : Bg), e.Bounds);
            if (e.Index < 0) { TextRenderer.DrawText(e.Graphics, drives.Items.Count == 0 ? "No USB drive found. Plug one in." : "", Font, e.Bounds, Mute, TextFormatFlags.VerticalCenter); return; }
            var d = (Drive)drives.Items[e.Index];
            TextRenderer.DrawText(e.Graphics, d.Label + (d.HasLaunchOS ? "  ·  " + Images.Describe(d.LaunchOSVersion) : ""), Font, Rectangle.Inflate(e.Bounds, -4, 0), Ink, TextFormatFlags.VerticalCenter | TextFormatFlags.EndEllipsis);
        }

        /// <summary>A question in a box. While it's open, plugging drives in or out changes nothing.</summary>
        DialogResult Ask(string text, string caption, MessageBoxButtons buttons, MessageBoxIcon icon)
        {
            asking = true; deviceTimer.Stop();
            try { return MessageBox.Show(this, text, caption, buttons, icon); }
            finally { asking = false; }
        }

        // ---------- what's newest ----------

        async Task CheckLatest()
        {
            var r = await Releases.Latest();
            latest = r.Item1; latestError = r.Item2;
            if (latest != null)
            {
                useNewest.Text = "Download the newest: LaunchOS " + latest.Version + " (" + Images.Size(latest.IsoSize) + ")";
                status.Text = "The newest is LaunchOS " + latest.Version + ".";
                if (file == null || !file.IsLaunchOS) useNewest.Checked = true;
                if (!string.IsNullOrEmpty(latest.FlasherUrl) && Images.CompareVersions(latest.Version, Program.Version) > 0)
                {
                    banner.Text = "A newer LaunchOS Flasher (" + latest.Version + ") is out. Click here to get it.";
                    banner.Visible = true;
                }
                OfferNewestFor(file);
            }
            else
            {
                status.Text = latestError + " You can still use a LaunchOS file you downloaded.";
                useNewest.Enabled = false;
                useFile.Checked = true;
            }
            UpdateState();
        }

        /// <summary>The picked file is older than what's out: ask whether to use the newest instead.</summary>
        void OfferNewestFor(ImageInfo f)
        {
            if (latest == null || f == null || !f.IsLaunchOS || !useFile.Checked) return;
            if (Images.CompareVersions(f.Version, latest.Version) >= 0) return;
            if (Ask(f.Name + " has " + Images.Describe(f.Version) + ", but LaunchOS " + latest.Version + " is out.\n\nDownload and use the newest instead?",
                "A newer LaunchOS is out", MessageBoxButtons.YesNo, MessageBoxIcon.Question) == DialogResult.Yes)
                useNewest.Checked = true;
        }

        void Browse()
        {
            asking = true;
            try
            {
                using (var dlg = new OpenFileDialog { Filter = "LaunchOS (LaunchOS.iso, LaunchOS.zip)|*.iso;*.zip|All files|*.*", Title = "Pick LaunchOS.iso or LaunchOS.zip" })
                {
                    if (dlg.ShowDialog(this) != DialogResult.OK) { if (file == null && latest != null) useNewest.Checked = true; return; }
                    try
                    {
                        file = Images.Inspect(dlg.FileName);
                        useFile.Checked = true;
                    }
                    catch (Exception ex) { asking = false; Ask("Couldn't open that file: " + ex.Message, "LaunchOS Flasher", MessageBoxButtons.OK, MessageBoxIcon.Warning); return; }
                }
            }
            finally { asking = false; UpdateState(); }
            OfferNewestFor(file);
            UpdateState();
        }

        // ---------- drives ----------

        async Task RefreshDrives(bool announce = false)
        {
            if (refreshing || busy) return;
            refreshing = true;
            try
            {
                var before = drives.Items.Cast<Drive>().Select(d => d.Identity).ToList();
                string keep = drives.SelectedItem is Drive cur ? cur.Identity : "";
                bool hard = showHard.Checked;
                string problem = "";
                var list = await Task.Run(() => Drives.List(hard, out problem));   // (slow drives never freeze the window)
                if (busy || asking) return;   // (something started meanwhile: leave the list as it was)
                drives.BeginUpdate();
                drives.Items.Clear();
                foreach (var d in list) drives.Items.Add(d);
                drives.EndUpdate();
                drives.SelectedItem = list.FirstOrDefault(d => d.Identity == keep) ?? list.FirstOrDefault();
                if (problem != "") driveNote.Tag = problem; else driveNote.Tag = null;
                UpdateState();
                if (!announce) return;
                // a drive just plugged in that has an older LaunchOS: offer to update it
                var fresh = list.FirstOrDefault(d => !before.Contains(d.Identity));
                string target = TargetVersion();
                if (fresh != null && fresh.HasLaunchOS && target != "" && Images.CompareVersions(fresh.LaunchOSVersion, target) < 0)
                {
                    drives.SelectedItem = fresh;
                    var picked = fresh;   // (this drive, whatever happens to the list while the question is open)
                    if (Ask(picked.Description + "\n\nhas " + Images.Describe(picked.LaunchOSVersion) + " on it. Update it to LaunchOS " + target + "?\n\nUpdating erases the drive, including any saves on it.",
                        "Update this USB drive?", MessageBoxButtons.YesNo, MessageBoxIcon.Question) == DialogResult.Yes)
                        BeginInvoke(new Action(async () => await Go(picked, true)));
                }
            }
            finally { refreshing = false; }
        }

        protected override void WndProc(ref Message m)
        {
            base.WndProc(ref m);
            const int WM_DEVICECHANGE = 0x219, DBT_DEVICEARRIVAL = 0x8000, DBT_DEVICEREMOVECOMPLETE = 0x8004;
            if (m.Msg == WM_DEVICECHANGE && ((int)m.WParam == DBT_DEVICEARRIVAL || (int)m.WParam == DBT_DEVICEREMOVECOMPLETE) && !busy && !asking)
            {
                deviceTimer.Stop(); deviceTimer.Start();   // drives show up in bursts: wait for them to settle
            }
        }

        // ---------- state ----------

        string TargetVersion() => useNewest.Checked && latest != null ? latest.Version : file != null && file.IsLaunchOS ? file.Version : "";

        void UpdateState()
        {
            browse.Enabled = useFile.Checked && !busy;
            fileLabel.Text = file == null ? "" : file.Name + " · " + (file.IsLaunchOS ? Images.Describe(file.Version) : "not LaunchOS") + " · " + Images.Size(file.Length);
            note.ForeColor = Warn;
            note.Text = "";
            if (useFile.Checked && file != null && !file.IsLaunchOS) note.Text = "This doesn't look like LaunchOS. Pick LaunchOS.iso or LaunchOS.zip.";
            else if (useFile.Checked && file != null && latest != null && Images.CompareVersions(file.Version, latest.Version) < 0)
                note.Text = "This file has " + Images.Describe(file.Version) + ". The newest is " + latest.Version + ".";
            var d = drives.SelectedItem as Drive;
            string target = TargetVersion();
            if (driveNote.Tag is string problem) driveNote.Text = problem;
            else if (d == null) driveNote.Text = "Plug in a USB drive of 4 GB or more. Everything on it will be erased.";
            else if (d.HasLaunchOS && target != "" && Images.CompareVersions(d.LaunchOSVersion, target) < 0)
                driveNote.Text = "This drive has " + Images.Describe(d.LaunchOSVersion) + ". Writing updates it to LaunchOS " + target + " (saves on the drive are erased).";
            else if (d.HasLaunchOS && target != "" && Images.CompareVersions(d.LaunchOSVersion, target) == 0)
                driveNote.Text = "This drive already has LaunchOS " + target + ". Writing it again erases the saves on it.";
            else driveNote.Text = "Everything on this drive will be erased.";
            bool ready = !busy && d != null && (useNewest.Checked ? latest != null : file != null && file.IsLaunchOS);
            write.Enabled = ready;
            write.BackColor = ready ? Accent : Line;
            write.Text = d != null && d.HasLaunchOS && target != "" && Images.CompareVersions(d.LaunchOSVersion, target) < 0 ? "Update to " + target : "Write LaunchOS";
            refresh.Enabled = drives.Enabled = useNewest.Enabled = useFile.Enabled = showHard.Enabled = !busy;
            if (latest == null) useNewest.Enabled = false;
        }

        // ---------- write ----------

        async Task Go(Drive d, bool asked)
        {
            if (busy || d == null) return;
            string what = useNewest.Checked && latest != null ? "LaunchOS " + latest.Version : file != null ? Images.Describe(file.Version) : "LaunchOS";
            if (!asked && Ask("Erase this drive and write " + what + " to it?\n\n" + d.Description + "\n\nEverything on the drive will be deleted.",
                "Write LaunchOS", MessageBoxButtons.OKCancel, MessageBoxIcon.Warning) != DialogResult.OK) return;
            busy = true; cts = new CancellationTokenSource();
            deviceTimer.Stop();
            meter.Visible = cancel.Visible = true; meter.Value = 0;
            work.ForeColor = Ink2;
            UpdateState();
            var writer = new Writer();
            try
            {
                ImageInfo image = file;
                if (useNewest.Checked && latest != null)
                {
                    work.Text = "Downloading LaunchOS " + latest.Version + "…";
                    var prog = new Progress<Tuple<long, long>>(p => { meter.Value = p.Item2 > 0 ? (double)p.Item1 / p.Item2 : 0; work.Text = "Downloading LaunchOS " + latest.Version + " · " + Images.Size(p.Item1) + " of " + Images.Size(p.Item2); });
                    var step = new Progress<string>(s => work.Text = s + "…");
                    string path = await Releases.DownloadIso(latest, prog, step, cts.Token);
                    image = await Task.Run(() => Images.Inspect(path));
                }
                if (image == null || !image.IsLaunchOS) throw new InvalidOperationException("That isn't LaunchOS. Pick LaunchOS.iso or LaunchOS.zip.");
                var started = Stopwatch.StartNew();
                var ui = SynchronizationContext.Current;
                writer.Progress = (s, n, total) => ui.Post(_ =>
                {
                    meter.Value = total > 0 ? (double)n / total : 0;
                    double secs = started.Elapsed.TotalSeconds;
                    string rate = secs > 2 && n > 0 && s.StartsWith("Writing") ? " · " + (n / secs / (1 << 20)).ToString("0") + " MB/s" : "";
                    work.Text = s + (total > 1 ? " · " + (100.0 * n / total).ToString("0") + "%" : "") + rate;
                }, null);
                var token = cts.Token;
                await Task.Run(() => writer.Write(d, image, true, token));
                meter.Value = 1;
                work.ForeColor = Accent;
                work.Text = "LaunchOS is on the drive. Plug it into a PC and start from it (the boot menu is usually F12, F8 or Esc). " +
                            "If it doesn't start, turn off Secure Boot in the PC's settings.";
            }
            catch (OperationCanceledException)
            {
                work.ForeColor = Warn;
                work.Text = writer.Touched ? "Stopped. The drive is blank now: write LaunchOS again, or make it a normal drive in Disk Management (right-click Start)."
                                           : "Stopped. Nothing was written.";
            }
            catch (Exception ex)
            {
                work.ForeColor = Bad;
                work.Text = ex.Message + (writer.Touched ? " The drive was left blank." : "");
            }
            finally
            {
                busy = false; cancel.Visible = false;
                UpdateState();
            }
            if (closeWhenDone) { Close(); return; }
            await RefreshDrives();
        }

        void OnClosing(object sender, FormClosingEventArgs e)
        {
            if (!busy || closeWhenDone) return;
            e.Cancel = true;
            if (Ask("LaunchOS is still being written. Stop and close? The drive will be left blank.", "LaunchOS Flasher",
                MessageBoxButtons.YesNo, MessageBoxIcon.Warning) != DialogResult.Yes) return;
            closeWhenDone = true;   // closes once the writer has really stopped (it leaves the drive in a clean state first)
            cts?.Cancel();
            work.Text = "Stopping…";
        }

        /// <summary>Opens a web page in the person's own browser (not as administrator, like this program runs).</summary>
        void OpenPage(string url)
        {
            if (string.IsNullOrEmpty(url)) url = "https://github.com/" + Releases.Repo + "/releases/latest";
            if (!url.StartsWith("https://")) return;
            try { Process.Start(new ProcessStartInfo("explorer.exe", "\"" + url + "\"") { UseShellExecute = false }); }
            catch { try { Process.Start(url); } catch { } }
        }
    }

    /// <summary>A panel with rounded corners and a thin border.</summary>
    class RoundPanel : Panel
    {
        public Color Border;
        public RoundPanel() { DoubleBuffered = true; }
        protected override void OnPaint(PaintEventArgs e)
        {
            e.Graphics.SmoothingMode = SmoothingMode.AntiAlias;
            using (var path = Round(new Rectangle(0, 0, Width - 1, Height - 1), 12))
            using (var pen = new Pen(Border)) e.Graphics.DrawPath(pen, path);
        }
        protected override void OnResize(EventArgs e)
        {
            base.OnResize(e);
            using (var path = Round(new Rectangle(0, 0, Width, Height), 12)) Region = new Region(path);
        }
        public static GraphicsPath Round(Rectangle r, int radius)
        {
            var p = new GraphicsPath();
            int d = radius * 2;
            p.AddArc(r.X, r.Y, d, d, 180, 90); p.AddArc(r.Right - d, r.Y, d, d, 270, 90);
            p.AddArc(r.Right - d, r.Bottom - d, d, d, 0, 90); p.AddArc(r.X, r.Bottom - d, d, d, 90, 90);
            p.CloseFigure();
            return p;
        }
    }

    /// <summary>The progress bar.</summary>
    class Meter : Control
    {
        double value;
        public double Value { get => value; set { this.value = Math.Max(0, Math.Min(1, value)); Invalidate(); } }
        public Meter() { DoubleBuffered = true; }
        protected override void OnPaint(PaintEventArgs e)
        {
            e.Graphics.SmoothingMode = SmoothingMode.AntiAlias;
            e.Graphics.Clear(Parent.BackColor);
            using (var track = RoundPanel.Round(new Rectangle(0, 0, Width - 1, Height - 1), Height / 2))
                e.Graphics.FillPath(new SolidBrush(Color.FromArgb(26, 43, 64)), track);
            int w = (int)((Width - 1) * value);
            if (w >= Height)
                using (var fill = RoundPanel.Round(new Rectangle(0, 0, w, Height - 1), Height / 2))
                    e.Graphics.FillPath(new SolidBrush(Color.FromArgb(61, 220, 107)), fill);
        }
    }
}
