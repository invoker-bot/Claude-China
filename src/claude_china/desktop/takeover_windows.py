"""Explicit, reversible, exact-path Windows registration for Grok Bot only."""

import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid

from ..config_paths import config_dir
from .takeover import checked_target, validate_manifest
from .takeover_native import hook_path

KEY = r'SOFTWARE\Microsoft\Windows NT\CurrentVersion\Image File Execution Options\Grok Bot.exe'
FILTER = 'ClaudeChinaLaunchGuard'
OWNER = 'ClaudeChinaLaunchGuardOwner'


def manifest_path():
    return config_dir() / 'takeover/grok-bot.json'


def debugger_command(manifest, path):
    return subprocess.list2cmdline([manifest['broker'], '--takeover-launch', str(path), '--'])


def read_registration():
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, KEY, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as root:
            owner = winreg.QueryValueEx(root, OWNER)[0]
            enabled = winreg.QueryValueEx(root, 'UseFilter')[0]
            with winreg.OpenKey(root, FILTER) as key:
                return {'owner': owner, 'enabled': enabled,
                        'target': winreg.QueryValueEx(key, 'FilterFullPath')[0],
                        'debugger': winreg.QueryValueEx(key, 'Debugger')[0]}
    except FileNotFoundError:
        return None


def get_status():
    supported = sys.platform == 'win32' and getattr(sys, 'frozen', False) and hook_path().is_file()
    result = {'supported': supported, 'enabled': False,
              'message': '仅 Windows 安装版支持 Grok Bot 原入口接管。' if not supported else '未接管原入口。'}
    if sys.platform != 'win32':
        return result
    try:
        path = manifest_path()
        manifest = json.loads(path.read_text(encoding='utf-8'))
        current = read_registration()
        result['enabled'] = bool(current and current == {
            'owner': manifest['owner'], 'enabled': 1, 'target': manifest['target'],
            'debugger': debugger_command(manifest, path)})
        if result['enabled']:
            result.update(target=manifest['target'], message='已接管原入口；每次启动和更新后重启都会重新检查并注入变量。')
        elif current:
            result['message'] = '接管注册与本机配置不一致，请先停用后重新启用。'
    except (OSError, ValueError, KeyError):
        pass
    return result


def apply_registration(path, enable):
    """Elevated helper. Refuse foreign IFEO keys and altered debugger values."""
    import winreg
    path = Path(path).resolve(strict=True)
    manifest = json.loads(path.read_text(encoding='utf-8'))
    # Removal still works after the vendor application has been uninstalled.
    if (manifest.get('schema') != 1 or manifest.get('app_id') != 'grok-bot'
            or Path(manifest['target']).name.lower() != 'grok bot.exe'
            or len(manifest.get('owner', '')) != 32
            or Path(manifest['broker']).resolve() != Path(sys.executable).resolve()):
        raise ValueError('接管配置不属于此启动器。')
    if enable:
        validate_manifest(manifest, [manifest['target']])
        if not hook_path().is_file():
            raise ValueError('缺少本机兼容组件。')
    access = winreg.KEY_READ | winreg.KEY_WRITE | winreg.KEY_WOW64_64KEY
    command = debugger_command(manifest, path)
    try:
        root = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, KEY, 0, access)
    except FileNotFoundError:
        if not enable:
            return
        root = winreg.CreateKeyEx(winreg.HKEY_LOCAL_MACHINE, KEY, 0, access)
        with root:
            if winreg.QueryInfoKey(root)[:2] != (0, 0):
                raise ValueError('接管注册已存在，未覆盖它。')
            try:
                winreg.SetValueEx(root, OWNER, 0, winreg.REG_SZ, manifest['owner'])
                with winreg.CreateKeyEx(root, FILTER, 0, access) as child:
                    winreg.SetValueEx(child, 'FilterFullPath', 0, winreg.REG_SZ, manifest['target'])
                    winreg.SetValueEx(child, 'Debugger', 0, winreg.REG_SZ, command)
                winreg.SetValueEx(root, 'UseFilter', 0, winreg.REG_DWORD, 1)
            except Exception:
                # The parent was created by this invocation, with no foreign data.
                try:
                    winreg.DeleteKey(root, FILTER)
                except FileNotFoundError:
                    pass
                winreg.DeleteKeyEx(winreg.HKEY_LOCAL_MACHINE, KEY, winreg.KEY_WOW64_64KEY)
                raise
        return
    with root:
        current = read_registration()
        expected = {'owner': manifest['owner'], 'enabled': 1,
                    'target': manifest['target'], 'debugger': command}
        if current != expected:
            raise ValueError('检测到其他接管配置或注册已被修改；未覆盖它。')
        if enable:
            return
        with winreg.OpenKey(root, FILTER, 0, access) as child:
            winreg.DeleteValue(child, 'Debugger')
            winreg.DeleteValue(child, 'FilterFullPath')
            empty = winreg.QueryInfoKey(child)[:2] == (0, 0)
        if empty:
            winreg.DeleteKey(root, FILTER)
        winreg.DeleteValue(root, OWNER)
        if winreg.QueryInfoKey(root)[0] == 0:
            winreg.DeleteValue(root, 'UseFilter')
        empty = winreg.QueryInfoKey(root)[:2] == (0, 0)
    if empty:
        winreg.DeleteKeyEx(winreg.HKEY_LOCAL_MACHINE, KEY, winreg.KEY_WOW64_64KEY)


def _elevate(path, enable):
    class ExecuteInfo(ctypes.Structure):
        _fields_ = [('cbSize', wintypes.DWORD), ('fMask', ctypes.c_ulong), ('hwnd', wintypes.HWND),
                    ('lpVerb', wintypes.LPCWSTR), ('lpFile', wintypes.LPCWSTR), ('lpParameters', wintypes.LPCWSTR),
                    ('lpDirectory', wintypes.LPCWSTR), ('nShow', ctypes.c_int), ('hInstApp', wintypes.HINSTANCE),
                    ('lpIDList', ctypes.c_void_p), ('lpClass', wintypes.LPCWSTR), ('hkeyClass', wintypes.HKEY),
                    ('dwHotKey', wintypes.DWORD), ('hIcon', wintypes.HANDLE), ('hProcess', wintypes.HANDLE)]
    parameters = subprocess.list2cmdline(['--takeover-register', str(path)] + ([] if enable else ['--disable']))
    info = ExecuteInfo()
    info.cbSize, info.fMask = ctypes.sizeof(info), 0x40
    info.lpVerb, info.lpFile, info.lpParameters, info.nShow = 'runas', sys.executable, parameters, 0
    shell = ctypes.WinDLL('shell32', use_last_error=True)
    shell.ShellExecuteExW.argtypes = [ctypes.POINTER(ExecuteInfo)]
    if not shell.ShellExecuteExW(ctypes.byref(info)):
        raise OSError('管理员授权被取消，接管设置未更改。')
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    try:
        # The app remains responsive while this bridge request waits for UAC.
        if kernel.WaitForSingleObject(info.hProcess, 120000) != 0:
            raise OSError('接管设置仍未完成，请检查管理员授权窗口。')
        code = wintypes.DWORD()
        if not kernel.GetExitCodeProcess(info.hProcess, ctypes.byref(code)) or code.value:
            raise OSError('无法修改接管注册；可能已有其他接管配置。')
    finally:
        kernel.CloseHandle(info.hProcess)


def set_enabled(enable, target=None):
    if sys.platform != 'win32' or (enable and not get_status()['supported']):
        raise ValueError('请使用 Windows 安装版设置全局接管。')
    path = manifest_path()
    if enable:
        target = checked_target(target)
        if path.is_file():
            manifest = json.loads(path.read_text(encoding='utf-8'))
            if read_registration() and (manifest['target'] != str(target) or manifest['broker'] != sys.executable):
                raise ValueError('请先停用接管，再更改应用或启动器路径。')
        else:
            manifest = {'schema': 1, 'app_id': 'grok-bot', 'owner': uuid.uuid4().hex}
        manifest.update(target=str(target), broker=sys.executable)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix('.tmp')
        temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
        os.replace(temporary, path)
    elif not path.exists() or read_registration() is None:
        return get_status()
    if ctypes.windll.shell32.IsUserAnAdmin():
        apply_registration(path, enable)
    else:
        _elevate(path, enable)
    return get_status()


def uninstall():
    if sys.platform == 'win32':
        path = manifest_path()
        if path.exists():
            set_enabled(False)
        else:
            current = read_registration()
            if current and current['debugger'] == debugger_command({'broker': sys.executable}, path):
                raise ValueError('接管配置文件缺失，请恢复配置并停用接管后再卸载。')
    return 0
