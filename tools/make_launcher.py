"""소스 실행용 시작 프로그램을 만든다: .venv\\Scripts\\모비 커넥터 리모콘.exe

venv 의 pythonw 는 스토어 파이썬이라 관리자 권한 확인 창과 작업 표시줄에 'Python' 이 뜬다.
이 exe 는 앱 이름·아이콘으로 관리자 권한을 받고 pythonw gui.py 를 띄운다 (tools/launcher.cs).
윈도에 들어 있는 .NET Framework 컴파일러(csc.exe)로 만든다. 배포판(exe)과는 상관없다.

    .venv\\Scripts\\python.exe tools\\make_launcher.py [--shortcut 바로가기.lnk]
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NAME = "모비 커넥터 리모콘.exe"
TARGET = ROOT / ".venv" / "Scripts" / NAME

MANIFEST = """<?xml version="1.0" encoding="utf-8" standalone="yes"?>
<assembly xmlns="urn:schemas-microsoft-com:asm.v1" manifestVersion="1.0">
  <assemblyIdentity version="1.0.0.0" name="MobiRemote.Launcher"/>
  <trustInfo xmlns="urn:schemas-microsoft-com:asm.v2">
    <security>
      <requestedPrivileges xmlns="urn:schemas-microsoft-com:asm.v3">
        <requestedExecutionLevel level="requireAdministrator" uiAccess="false"/>
      </requestedPrivileges>
    </security>
  </trustInfo>
</assembly>
"""


def csc() -> Path:
    windir = Path(os.environ.get("WINDIR", r"C:\Windows"))
    for fw in ("Framework64", "Framework"):
        found = sorted((windir / "Microsoft.NET" / fw).glob("v4*/csc.exe"))
        if found:
            return found[-1]
    raise SystemExit("csc.exe 를 찾지 못했습니다 (.NET Framework 4)")


def build(out: Path = TARGET) -> Path:
    tmp = out.with_suffix(".manifest")
    tmp.write_text(MANIFEST, encoding="utf-8")
    try:
        cmd = [str(csc()), "/nologo", "/target:winexe", "/optimize+", "/codepage:65001",
               f"/out:{out}", f"/win32icon:{ROOT / 'tools' / 'icon.ico'}", f"/win32manifest:{tmp}",
               str(ROOT / "tools" / "launcher.cs")]
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="cp949", errors="replace")
        if r.returncode != 0:
            raise SystemExit(f"컴파일 실패\n{r.stdout}{r.stderr}")
    finally:
        tmp.unlink(missing_ok=True)
    return out


def shortcut(lnk: Path, exe: Path) -> None:
    """바로가기가 시작 프로그램을 가리키게 한다 (아이콘은 exe 안의 것)."""
    ps = ("$s=(New-Object -ComObject WScript.Shell).CreateShortcut($env:LNK);"
          "$s.TargetPath=$env:EXE;$s.Arguments='';$s.WorkingDirectory=$env:ROOT;$s.IconLocation=$env:EXE+',0';$s.Save()")
    env = dict(os.environ, LNK=str(lnk), EXE=str(exe), ROOT=str(ROOT))
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=True, env=env)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--shortcut", type=Path, help="이 바로가기(.lnk)가 시작 프로그램을 가리키게 고친다")
    a = ap.parse_args()
    if sys.platform != "win32":
        raise SystemExit("윈도 전용")
    exe = build()
    print(f"만듦: {exe}")
    if a.shortcut:
        shortcut(a.shortcut, exe)
        print(f"바로가기 고침: {a.shortcut}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
