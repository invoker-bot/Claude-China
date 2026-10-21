"""Independent, reversible Windows launch registrations for stable EXE paths."""

import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import uuid

from ..config_paths import config_dir
from .takeover import WINDOWS_EXECUTABLES, checked_target, validate_manifest
from .takeover_native import hook_path

ROOT = r'SOFTWARE\Microsoft\Windows NT\CurrentVersion\Image File Execution Options'
# Kept for callers of the original Grok-only API and existing installations.
KEY = ROOT + r'\Grok Bot.exe'
FILTER = 'ClaudeChinaLaunchGuard'
OWNER = 'ClaudeChinaLaunchGuardOwner'


def registry_key(app_id='grok-bot'):
    if app_id not in WINDOWS_EXECUTABLES:
        raise ValueError('未知的接管应用。')
    return ROOT + '\\' + WINDOWS_EXECUTABLES[app_id]


def manifest_path(app_id='grok-bot'):
    registry_key(app_id)
    return config_dir() / 'takeover' / (app_id + '.json')


def supported_target(target, app_id='grok-bot'):
    target = checked_target(target, app_id)
    # An explicit WindowsApps EXE selection must not bypass MSIX detection.
    # A path filter cannot follow changing package/version directories, and
    # launching a package binary directly does not preserve broker activation.
    for parent in target.parents:
        if parent.name.lower() == 'windowsapps' or (parent / 'AppxManifest.xml').is_file():
            raise ValueError('MSIX 安装暂不支持原入口接管，尚不能保证更新后的检查和包激活上下文。')
        if re.match(r'^app-\d', parent.name, re.IGNORECASE):
            raise ValueError('此安装路径包含版本目录，更新会改变路径，暂不支持持续接管。')
    return target


def debugger_command(manifest, path):
    return subprocess.list2cmdline([manifest['broker'], '--takeover-launch', str(path), '--'])


def read_registration(app_id='grok-bot'):
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, registry_key(app_id), 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as root:
            owner = winreg.QueryValueEx(root, OWNER)[0]
            enabled = winreg.QueryValueEx(root, 'UseFilter')[0]
            with winreg.OpenKey(root, FILTER) as key:
                return {'owner': owner, 'enabled': enabled,
                        'target': winreg.QueryValueEx(key, 'FilterFullPath')[0],
                        'debugger': winreg.QueryValueEx(key, 'Debugger')[0]}
    except FileNotFoundError:
        return None


def get_status(app_id='grok-bot', status=None):
    registry_key(app_id)
    supported = sys.platform == 'win32' and getattr(sys, 'frozen', False) and hook_path().is_file()
    result = {'app_id': app_id, 'supported': supported, 'enabled': False, 'can_disable': False,
              'mode': 'windows-exact-path',
              'message': '请使用 Windows 安装版设置原入口接管。' if not supported else '未接管原入口。仅覆盖固定 EXE 路径及同路径更新。'}
    if status is not None:
        try:
            if not status.found:
                raise ValueError('未找到应用，请先保存正确的应用路径。')
            if not status.direct:
                result['mode'] = 'msix-unavailable'
                raise ValueError('MSIX 安装暂不支持原入口接管，尚不能保证更新后的检查和包激活上下文。')
            supported_target(status.launch_target, app_id)
        except (ValueError, OSError) as exc:
            result.update(supported=False, message=str(exc))
    if sys.platform != 'win32':
        return result
    try:
        current = read_registration(app_id)
        path = manifest_path(app_id)
        if not path.is_file():
            if current:
                result.update(supported=False, message='接管配置文件缺失，无法确认保护状态。请恢复配置后再停用接管。')
            return result
        manifest = json.loads(path.read_text(encoding='utf-8'))
        validate_manifest(manifest, [manifest.get('target')], must_exist=False)
        if manifest['app_id'] != app_id:
            raise ValueError('接管应用不一致。')
        owned = bool(current and current == {
            'owner': manifest['owner'], 'enabled': 1, 'target': manifest['target'],
            'debugger': debugger_command(manifest, path)})
        result['can_disable'] = owned
        target = Path(manifest['target'])
        try:
            supported_target(target, app_id)
            valid_target = True
        except (ValueError, OSError):
            valid_target = False
        matches = status is None or (status.found and status.direct and Path(status.launch_target).resolve() == target)
        result['enabled'] = owned and matches and valid_target
        if result['enabled']:
            result.update(target=str(target), message='已接管此 EXE 原入口及同路径更新重启；每次重新检查并注入变量。')
        elif owned:
            result.update(supported=False, message='接管仍注册在旧路径或不再支持的安装位置，当前入口不受保护。请先停用，再选择受支持的路径重新启用。')
        elif current:
            result.update(supported=False, message='接管注册与配置不一致，无法确认保护状态。请恢复原配置后再停用接管。')
    except (OSError, ValueError, KeyError, TypeError):
        result.update(supported=False, message='无法读取或验证接管配置，当前保护状态未知。')
    return result


def apply_registration(path, enable):
    """Elevated helper. Refuse foreign IFEO keys and altered debugger values."""
    import winreg
    path = Path(path).resolve(strict=True)
    manifest = json.loads(path.read_text(encoding='utf-8'))
    # Removal still works after the vendor application has been uninstalled.
    validate_manifest(manifest, [manifest.get('target')], must_exist=enable)
    app_id = manifest['app_id']
    key_path = registry_key(app_id)
    if Path(manifest['broker']).resolve() != Path(sys.executable).resolve():
        raise ValueError('接管配置不属于此启动器。')
    if enable:
        supported_target(manifest['target'], app_id)
        if not hook_path().is_file():
            raise ValueError('缺少本机兼容组件。')
    access = winreg.KEY_READ | winreg.KEY_WRITE | winreg.KEY_WOW64_64KEY
    command = debugger_command(manifest, path)
    try:
        root = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path, 0, access)
    except FileNotFoundError:
        if not enable:
            return
        root = winreg.CreateKeyEx(winreg.HKEY_LOCAL_MACHINE, key_path, 0, access)
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
                winreg.DeleteKeyEx(winreg.HKEY_LOCAL_MACHINE, key_path, winreg.KEY_WOW64_64KEY)
                raise
        return
    with root:
        current = read_registration(app_id)
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
        winreg.DeleteKeyEx(winreg.HKEY_LOCAL_MACHINE, key_path, winreg.KEY_WOW64_64KEY)


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


def set_enabled(enable, target=None, app_id='grok-bot'):
    if sys.platform != 'win32' or (enable and not get_status(app_id)['supported']):
        raise ValueError('请使用 Windows 安装版设置全局接管。')
    path = manifest_path(app_id)
    if enable:
        target = supported_target(target, app_id)
        if path.is_file():
            manifest = json.loads(path.read_text(encoding='utf-8'))
            validate_manifest(manifest, [manifest.get('target')], must_exist=False)
            if manifest['app_id'] != app_id:
                raise ValueError('接管配置属于其他应用。')
            if read_registration(app_id) and (manifest['target'] != str(target) or manifest['broker'] != sys.executable):
                raise ValueError('请先停用接管，再更改应用或启动器路径。')
        else:
            manifest = {'schema': 1, 'app_id': app_id, 'owner': uuid.uuid4().hex}
        manifest.update(target=str(target), broker=sys.executable)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix('.tmp')
        temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
        os.replace(temporary, path)
    elif not path.exists() or read_registration(app_id) is None:
        return get_status(app_id)
    if ctypes.windll.shell32.IsUserAnAdmin():
        apply_registration(path, enable)
    else:
        _elevate(path, enable)
    return get_status(app_id)


def uninstall():
    if sys.platform == 'win32':
        for app_id in WINDOWS_EXECUTABLES:
            path = manifest_path(app_id)
            if path.exists():
                set_enabled(False, app_id=app_id)
            else:
                current = read_registration(app_id)
                if current and current['debugger'] == debugger_command({'broker': sys.executable}, path):
                    raise ValueError('接管配置文件缺失，请恢复配置并停用接管后再卸载。')
    return 0
