// LaunchOS Flasher: writes LaunchOS to a USB drive on Windows.
//   LaunchOSFlasher.exe                          the window
//   LaunchOSFlasher.exe --self-test LOG          checks (used when it's built)
//   LaunchOSFlasher.exe --write-test-vhd VHD IMAGE LOG   writes IMAGE to the small virtual disk the VHD
//                                                file VHD is attached as (only for the automatic tests;
//                                                it refuses any real drive)
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
            if (args.Length >= 4 && args[0] == "--write-test-vhd") return SelfTest.WriteTest(args[1], args[2], args[3]);
            if (args.Length >= 3 && args[0] == "--make-test-image") return SelfTest.MakeFake(args[1], args[2]);
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);
            Application.Run(new MainForm());
            return 0;
        }
    }
}
