using System;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Text;
using System.Windows.Forms;

[assembly: AssemblyTitle("文矩")]
[assembly: AssemblyDescription("文矩 · 文档格式整理系统")]
[assembly: AssemblyProduct("文矩")]
[assembly: AssemblyCompany("WenJu")]
[assembly: AssemblyVersion("3.2.1.0")]
[assembly: AssemblyFileVersion("3.2.1.0")]

internal static class Launcher {
    private static string Quote(string value) {
        var sb = new StringBuilder("\"");
        int slashes = 0;
        foreach (char ch in value) {
            if (ch == '\\') { slashes++; continue; }
            if (ch == '"') { sb.Append('\\', slashes * 2 + 1); sb.Append(ch); }
            else { sb.Append('\\', slashes); sb.Append(ch); }
            slashes = 0;
        }
        sb.Append('\\', slashes * 2); sb.Append('"'); return sb.ToString();
    }
    [STAThread]
    private static int Main(string[] args) {
        Application.EnableVisualStyles();
        string home = AppDomain.CurrentDomain.BaseDirectory;
        string python = Path.Combine(home, "runtime", "pythonw.exe");
        string app = Path.Combine(home, "app.py");
        if (!File.Exists(python) || !File.Exists(app)) {
            MessageBox.Show("请先完整解压文矩便携包，并保留 EXE 旁的 runtime、core 和程序文件。", "文矩 · 启动提示", MessageBoxButtons.OK, MessageBoxIcon.Information);
            return 1;
        }
        try {
            var arguments = new StringBuilder(Quote(app));
            foreach (string arg in args) arguments.Append(" ").Append(Quote(arg));
            Process.Start(new ProcessStartInfo {
                FileName = python, Arguments = arguments.ToString(), WorkingDirectory = home,
                UseShellExecute = false, CreateNoWindow = true
            });
            return 0;
        } catch (Exception ex) {
            MessageBox.Show("无法启动文矩：\n" + ex.Message, "文矩", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return 1;
        }
    }
}
