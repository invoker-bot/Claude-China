"""Build the x64 Grok child-creation hook with pinned Microsoft Detours sources."""

import hashlib
import io
import os
from pathlib import Path
import subprocess
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / 'build/desktop/native'
URL = 'https://codeload.github.com/microsoft/Detours/zip/refs/tags/v4.0.1'
SHA256 = '5ab84eb08fb9befeb16ffd04ca283731b1e0e1e53b1947ce7868d4b9654e43fc'


def build():
    WORK.mkdir(parents=True, exist_ok=True)
    archive = WORK / 'Detours-v4.0.1.zip'
    if not archive.exists():
        with urllib.request.urlopen(URL, timeout=60) as response:
            archive.write_bytes(response.read())
    data = archive.read_bytes()
    if hashlib.sha256(data).hexdigest() != SHA256:
        raise RuntimeError('Detours source checksum mismatch')
    sources = WORK / 'detours'
    with zipfile.ZipFile(io.BytesIO(data)) as zipped:
        # Extract only the pinned library inputs, never arbitrary archive paths.
        for item in zipped.infolist():
            relative = Path(*Path(item.filename).parts[1:])
            if item.is_dir() or '..' in relative.parts:
                continue
            if str(relative) not in ('LICENSE.md', 'system.mak') and relative.parts[:1] != ('src',):
                continue
            destination = sources / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(zipped.read(item))
    vswhere = Path(os.environ.get('ProgramFiles(x86)', 'C:/Program Files (x86)')) / 'Microsoft Visual Studio/Installer/vswhere.exe'
    setup = subprocess.check_output([str(vswhere), '-latest', '-products', '*', '-requires',
        'Microsoft.VisualStudio.Component.VC.Tools.x86.x64', '-find', 'VC/Auxiliary/Build/vcvars64.bat'], text=True).strip()
    if not setup or not Path(setup).is_file():
        raise RuntimeError('Visual Studio C++ x64 Build Tools are required')
    native = ROOT / 'native/windows'
    script = WORK / 'build.cmd'
    script.write_text('\n'.join([
        '@echo off', f'call "{setup}" >nul', 'if errorlevel 1 exit /b 1',
        f'cd /d "{sources / "src"}"', 'nmake /nologo', 'if errorlevel 1 exit /b 1',
        f'cd /d "{WORK}"',
        f'cl /nologo /LD /MT /O2 /EHsc /W4 /WX /I"{sources / "src"}" "{native / "takeover_hook.cpp"}" /link "{sources / "lib.X64/detours.lib"}" kernel32.lib advapi32.lib shell32.lib /DEF:"{native / "takeover_hook.def"}" /OUT:claudec-child-hook.dll',
        'exit /b %errorlevel%',
    ]) + '\n', encoding='utf-8')
    subprocess.run(['cmd.exe', '/d', '/c', str(script)], check=True, cwd=WORK)
    return WORK / 'claudec-child-hook.dll'


if __name__ == '__main__':
    print(build())
