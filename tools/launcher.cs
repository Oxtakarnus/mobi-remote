// 소스로 쓸 때의 시작 프로그램 (tools/make_launcher.py 가 .venv\Scripts 에 만든다).
// venv 의 pythonw 를 바로 켜면 관리자 권한 확인 창과 작업 표시줄에 'Python' 이 뜬다.
// 이 exe 가 앱 이름·아이콘으로 관리자 권한을 받고, 같은 권한으로 pythonw gui.py 를 띄운 뒤 끝난다.
using System;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Text;
using System.Windows.Forms;

[assembly: AssemblyTitle("모비 커넥터 리모콘")]
[assembly: AssemblyProduct("모비 커넥터 리모콘")]
[assembly: AssemblyDescription("모비 커넥터 리모콘 (소스 실행)")]
[assembly: AssemblyVersion("1.0.0.0")]
[assembly: AssemblyFileVersion("1.0.0.0")]

static class Launcher
{
    static string Quote(string a)
    {
        return "\"" + a.Replace("\"", "\\\"") + "\"";
    }

    [STAThread]
    static int Main(string[] args)
    {
        string here = AppDomain.CurrentDomain.BaseDirectory;          // <저장소>\.venv\Scripts\
        string root = Path.GetFullPath(Path.Combine(here, "..", ".."));
        string py = Path.Combine(here, "pythonw.exe");
        string gui = Path.Combine(root, "gui.py");
        if (!File.Exists(py) || !File.Exists(gui))
        {
            MessageBox.Show("pythonw.exe 또는 gui.py 를 찾지 못했습니다.\n" + py + "\n" + gui, "모비 커넥터 리모콘");
            return 1;
        }
        var line = new StringBuilder(Quote(gui));
        foreach (string a in args)
            line.Append(' ').Append(Quote(a));
        var psi = new ProcessStartInfo(py, line.ToString());
        psi.UseShellExecute = false;
        psi.WorkingDirectory = root;
        Process.Start(psi);
        return 0;
    }
}
