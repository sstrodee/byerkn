using System;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Windows.Forms;

[assembly: AssemblyTitle("byerkn")]
[assembly: AssemblyProduct("byerkn")]
[assembly: AssemblyFileVersion("1.0.0.0")]
[assembly: AssemblyVersion("1.0.0.0")]

static class Launcher {
    [STAThread]
    static void Main() {
        string root = AppDomain.CurrentDomain.BaseDirectory;
        string python = Path.Combine(root, "runtime", "pythonw.exe");
        if (!File.Exists(python)) {
            MessageBox.Show("Распакуйте всю папку byerkn. Рядом с программой должна быть папка runtime.", "byerkn", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return;
        }
        try {
            var start = new ProcessStartInfo(python, "-m byerkn");
            start.WorkingDirectory = root;
            start.UseShellExecute = false;
            start.CreateNoWindow = true;
            start.EnvironmentVariables["QT_QPA_PLATFORM"] = "windows:fontengine=freetype";
            Process.Start(start);
        } catch (Exception ex) {
            MessageBox.Show(ex.Message, "Не удалось открыть byerkn", MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
    }
}
