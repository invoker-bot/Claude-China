"""Open native terminals and pass a single-use, credential-free launch request."""

import base64
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import time
import uuid

from ..config_paths import config_dir
from ..launcher import find_command
from . import process

PACKAGES = {'claude': '@anthropic-ai/claude-code', 'codex': '@openai/codex', 'grok': '@xai-official/grok'}


def resolve_cli_argv(kind):
    command = find_command(kind)
    if not command:
        raise ValueError(f'未找到 {kind} CLI，请先安装并确保命令在 PATH 中。')
    path = Path(command)
    if sys.platform != 'win32' or path.suffix.lower() not in ('.cmd', '.bat', '.ps1'):
        return [str(path)]
    # Invoke the npm package entry directly. A .cmd shell can reinterpret
    # user-supplied arguments (% expansion, &, quotes) even with shell=False.
    package = path.parent / 'node_modules' / PACKAGES[kind]
    try:
        metadata = json.loads((package / 'package.json').read_text(encoding='utf-8'))
        entry = metadata.get('bin', {})
        relative = entry.get(kind) if isinstance(entry, dict) else entry
        target = (package / relative).resolve(strict=True)
        if package.resolve() not in target.parents or not target.is_file():
            raise ValueError()
        if target.suffix.lower() == '.exe':
            return [str(target)]
        node = str(path.parent / 'node.exe') if (path.parent / 'node.exe').is_file() else shutil.which('node.exe')
        if not node:
            raise ValueError()
        return [node, str(target)]
    except (OSError, ValueError, TypeError):
        raise ValueError(f'无法识别 {kind} 的 npm 启动脚本，请检查该 CLI 和 Node.js 的安装。') from None


def jobs_dir():
    return config_dir() / 'terminal-jobs'


def create_job(profile, directory, session_id=None):
    root = jobs_dir()
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    for old in root.glob('*.json'):
        if re.fullmatch(r'[a-f0-9]{32}\.json', old.name) and old.stat().st_mtime < time.time() - 86400:
            old.unlink(missing_ok=True)
    path = root / (uuid.uuid4().hex + '.json')
    with os.fdopen(os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w', encoding='utf-8') as f:
        request = {'schema': 1, 'profile': profile, 'directory': directory, 'expires_at': time.time() + 300}
        if session_id is not None:
            request['session_id'] = session_id
        json.dump(request, f)
    return path


def consume_job(path):
    path = Path(path).resolve()
    if path.parent != jobs_dir().resolve() or not re.fullmatch(r'[a-f0-9]{32}\.json', path.name):
        raise ValueError('无效的终端启动请求。')
    claimed = path.with_suffix('.running')
    try:
        # Claim before reading so another worker cannot execute it twice.
        path.rename(claimed)
        try:
            data = json.loads(claimed.read_text(encoding='utf-8'))
        finally:
            claimed.unlink(missing_ok=True)
    except (OSError, ValueError):
        raise ValueError('终端启动请求已失效，请从启动器重试。') from None
    if (not isinstance(data, dict) or data.get('schema') != 1
            or not isinstance(data.get('expires_at'), (int, float)) or data['expires_at'] < time.time()):
        raise ValueError('终端启动请求已过期，请从启动器重试。')
    if data.get('profile') is not None and not isinstance(data['profile'], str):
        raise ValueError('无效的配置名称。')
    if 'session_id' in data and (not isinstance(data['session_id'], str) or data.get('profile') is None):
        raise ValueError('无效的会话恢复请求。')
    return data


def _helper(path):
    return [sys.executable] + ([] if getattr(sys, 'frozen', False) else ['-m', 'claude_china.desktop.entry']) + ['--terminal-session', str(path)]


def _ps_quote(value):
    return "'" + str(value).replace("'", "''") + "'"


def open_terminal(path, directory):
    helper = _helper(path)
    if sys.platform == 'win32':
        from .playwright_guard import prepare_environment as guard_environment
        env = guard_environment(os.environ)
        shell = shutil.which('pwsh.exe') or shutil.which('powershell.exe')
        if not shell:
            raise ValueError('未找到 PowerShell。')
        script = ('$OutputEncoding = [Console]::OutputEncoding = [Text.UTF8Encoding]::new(); '
                  'Start-Process -FilePath ' + _ps_quote(helper[0]) + ' -ArgumentList '
                  + _ps_quote(subprocess.list2cmdline(helper[1:])) + ' -Wait -NoNewWindow')
        encoded = base64.b64encode(script.encode('utf-16-le')).decode('ascii')
        process.Popen([shell, '-NoLogo', '-NoProfile', '-NoExit', '-EncodedCommand', encoded],
                      cwd=directory, creationflags=0x10, env=env)
    elif sys.platform == 'darwin':
        command = 'cd -- ' + shlex.quote(directory) + ' && ' + shlex.join(helper)
        script = 'on run argv\ntell application "Terminal"\nactivate\ndo script (item 1 of argv)\nend tell\nend run'
        result = process.run(['osascript', '-e', script, command], capture_output=True, timeout=30)
        if result.returncode:
            raise ValueError('无法打开 Terminal，请检查系统的自动化权限。')
    elif sys.platform == 'linux':
        for name, options in [('x-terminal-emulator', ['-e']), ('gnome-terminal', ['--']),
                              ('konsole', ['-e']), ('xfce4-terminal', ['--disable-server', '--execute']),
                              ('xterm', ['-e'])]:
            terminal = shutil.which(name)
            if terminal:
                shell = os.environ.get('SHELL') or '/bin/sh'
                command = 'cd -- "$1" || exit; shift; "$@"; exec ' + shlex.quote(shell) + ' -i'
                process.Popen([terminal] + options + ['/bin/sh', '-c', command, 'claudec-terminal', directory] + helper,
                              cwd=directory, start_new_session=True)
                return
        raise ValueError('未找到桌面终端，请安装 GNOME Terminal、Konsole 或 xterm。')
    else:
        raise ValueError('当前系统暂不支持打开终端。')


def open_directory(directory):
    from .terminals import directory_path
    directory = directory_path(directory)
    if sys.platform == 'win32':
        os.startfile(directory)
    else:
        process.Popen(['open', '--', directory] if sys.platform == 'darwin' else ['xdg-open', directory])


def _attach_console():
    if sys.platform == 'win32' and getattr(sys, 'frozen', False):
        import ctypes
        ctypes.windll.kernel32.AttachConsole(0xFFFFFFFF)
        ctypes.windll.kernel32.SetConsoleCP(65001)
        ctypes.windll.kernel32.SetConsoleOutputCP(65001)
        sys.stdin = open('CONIN$', 'r', encoding='utf-8')
        sys.stdout = open('CONOUT$', 'w', encoding='utf-8', buffering=1)
        sys.stderr = open('CONOUT$', 'w', encoding='utf-8', buffering=1)


def run_session(path):
    from .localization import display_message
    _attach_console()
    try:
        from .terminals import TerminalService, directory_path
        from .platforms import get_backend
        job = consume_job(path)
        directory = directory_path(job.get('directory'))
        if job['profile'] is None:
            return 0
        options = {'session_id': job['session_id']} if 'session_id' in job else {}
        argv, env = TerminalService(get_backend()).prepare(job['profile'], directory, **options)
        print('Claude China · ' + job['profile'], flush=True)
        # Credentials exist only in the child's environment, never terminal
        # history, shell source or the temporary launch request.
        return process.run(argv, cwd=directory, env=env).returncode
    except KeyboardInterrupt:
        return 130
    except ValueError as exc:
        print(display_message(str(exc)), file=sys.stderr)
        return 1
    except Exception:
        print(display_message('终端启动失败，请检查 CLI 安装和配置后重试。'), file=sys.stderr)
        return 1
