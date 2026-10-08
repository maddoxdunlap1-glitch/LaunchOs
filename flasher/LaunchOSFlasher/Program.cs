// LaunchOS Flasher: writes LaunchOS to a USB drive on Windows.
//   LaunchOSFlasher.exe                          the window
//   LaunchOSFlasher.exe --self-test LOG          checks (used when it's built)
//   LaunchOSFlasher.exe --write-test DISK IMAGE LOG   writes IMAGE to disk number DISK without asking,
//                                                even a drive inside the PC (only for the automatic tests)
using System;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Threading;
using System.Windows.Forms;

namespace LaunchOSFlasher
{
    static class Program
    {
        public static readonly string Version = TrimVersion(Assembly.GetExecutingAssembly().GetName().Version);

        static string TrimVersion(Version v) => v.Build > 0 ? v.Major + "." + v.Minor + "." + v.Build : v.Major + "." + v.Minor;

        [STAThread]
        static int Main(string[] args)
        {
            if (args.Length >= 2 && args[0] == "--self-test") return SelfTest.Run(args[1]);
            if (args.Length >= 4 && args[0] == "--write-test") return SelfTest.WriteTest(int.Parse(args[1]), args[2], args[3]);
            if (args.Length >= 3 && args[0] == "--make-test-image") return SelfTest.MakeFake(args[1], args[2]);
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);
            Application.Run(new MainForm());
            return 0;
        }
    }
}
