"""Exercise ownership and removal without writing the machine registry."""

from copy import deepcopy
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from claude_china.desktop import takeover_windows as registration


class Key:
    def __init__(self, path):
        self.path = path

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass


class Registry:
    HKEY_LOCAL_MACHINE = 'HKLM'
    KEY_READ = 1
    KEY_WRITE = 2
    KEY_WOW64_64KEY = 4
    REG_SZ = 1
    REG_DWORD = 4

    def __init__(self):
        self.data = {}

    def path(self, root, path):
        return (root.path + '\\' + path) if isinstance(root, Key) else path

    def OpenKey(self, root, path, *_):
        name = self.path(root, path)
        if name not in self.data:
            raise FileNotFoundError(name)
        return Key(name)

    def CreateKeyEx(self, root, path, *_):
        name = self.path(root, path)
        self.data.setdefault(name, {})
        return Key(name)

    def SetValueEx(self, key, name, _, kind, value):
        self.data[key.path][name] = (value, kind)

    def QueryValueEx(self, key, name):
        if name not in self.data[key.path]:
            raise FileNotFoundError(name)
        return self.data[key.path][name]

    def DeleteValue(self, key, name):
        del self.data[key.path][name]

    def QueryInfoKey(self, key):
        prefix = key.path + '\\'
        children = sum(name.startswith(prefix) and '\\' not in name[len(prefix):] for name in self.data)
        return children, len(self.data[key.path]), 0

    def DeleteKey(self, root, path, *_):
        name = self.path(root, path)
        if name not in self.data:
            raise FileNotFoundError(name)
        if self.QueryInfoKey(Key(name))[0]:
            raise OSError('Not empty')
        del self.data[name]

    DeleteKeyEx = DeleteKey


@pytest.fixture
def setup(tmp_path, monkeypatch):
    registry = Registry()
    monkeypatch.setitem(sys.modules, 'winreg', registry)
    target = tmp_path / 'Grok Bot.exe'
    target.touch()
    dll = tmp_path / 'hook.dll'
    dll.touch()
    monkeypatch.setattr(registration, 'hook_path', lambda: dll)
    manifest = {'schema': 1, 'app_id': 'grok-bot', 'owner': 'a' * 32,
                'broker': sys.executable, 'target': str(target)}
    path = tmp_path / 'manifest.json'
    path.write_text(json.dumps(manifest), encoding='utf-8')
    return SimpleNamespace(registry=registry, manifest=manifest, path=path, target=target)


def test_exact_path_registration_survives_replacement_and_is_idempotent(setup):
    registration.apply_registration(setup.path, True)
    before = deepcopy(setup.registry.data)
    setup.target.write_bytes(b'updated vendor executable')
    registration.apply_registration(setup.path, True)
    assert setup.registry.data == before
    assert registration.read_registration()['target'] == str(setup.target)
    assert '--takeover-launch' in registration.read_registration()['debugger']
    assert set(before) == {registration.KEY, registration.KEY + '\\' + registration.FILTER}


def test_registration_refuses_foreign_key_without_overwriting_any_value(setup):
    setup.registry.data[registration.KEY] = {'Debugger': ('foreign debugger', 1)}
    before = deepcopy(setup.registry.data)
    with pytest.raises(ValueError):
        registration.apply_registration(setup.path, True)
    assert setup.registry.data == before


def test_disable_still_works_after_vendor_uninstall(setup):
    registration.apply_registration(setup.path, True)
    setup.target.unlink()
    registration.apply_registration(setup.path, False)
    assert setup.registry.data == {}
    registration.apply_registration(setup.path, False)


def test_disable_preserves_other_filters_and_values(setup):
    registration.apply_registration(setup.path, True)
    setup.registry.data[registration.KEY]['ForeignValue'] = ('keep', 1)
    foreign = registration.KEY + '\\ForeignFilter'
    setup.registry.data[foreign] = {'FilterFullPath': ('another path', 1)}
    registration.apply_registration(setup.path, False)
    assert setup.registry.data == {registration.KEY: {'UseFilter': (1, 4), 'ForeignValue': ('keep', 1)},
                                   foreign: {'FilterFullPath': ('another path', 1)}}


def test_disable_refuses_changed_registration(setup):
    registration.apply_registration(setup.path, True)
    setup.registry.data[registration.KEY + '\\' + registration.FILTER]['Debugger'] = ('changed', 1)
    before = deepcopy(setup.registry.data)
    with pytest.raises(ValueError):
        registration.apply_registration(setup.path, False)
    assert setup.registry.data == before


def test_elevated_helper_cannot_register_another_broker_or_app(setup):
    for key, value in [('broker', str(Path(sys.executable).with_name('other.exe'))), ('app_id', 'claude')]:
        manifest = dict(setup.manifest, **{key: value})
        setup.path.write_text(json.dumps(manifest), encoding='utf-8')
        with pytest.raises(ValueError):
            registration.apply_registration(setup.path, True)
        assert setup.registry.data == {}


def test_uninstall_after_disable_does_not_request_admin_again(setup, monkeypatch):
    monkeypatch.setattr(registration.sys, 'platform', 'win32')
    monkeypatch.setattr(registration, 'manifest_path', lambda app_id='grok-bot': setup.path if app_id == 'grok-bot' else setup.path.with_name(app_id + '.json'))
    monkeypatch.setattr(registration, '_elevate', lambda *_: pytest.fail('Already disabled'))
    registration.apply_registration(setup.path, True)
    registration.apply_registration(setup.path, False)
    assert registration.uninstall() == 0


def test_uninstall_refuses_to_leave_owned_registration_without_manifest(setup, monkeypatch):
    monkeypatch.setattr(registration.sys, 'platform', 'win32')
    monkeypatch.setattr(registration, 'manifest_path', lambda app_id='grok-bot': setup.path if app_id == 'grok-bot' else setup.path.with_name(app_id + '.json'))
    registration.apply_registration(setup.path, True)
    setup.path.unlink()
    with pytest.raises(ValueError):
        registration.uninstall()


def test_three_registrations_are_independent_and_uninstall_cleans_each(setup, monkeypatch):
    paths = {}
    monkeypatch.setattr(registration.sys, 'platform', 'win32')
    monkeypatch.setattr(registration.ctypes, 'windll', SimpleNamespace(shell32=SimpleNamespace(IsUserAnAdmin=lambda: True)), raising=False)
    for app_id, name in [('grok-bot', 'Grok Bot.exe'), ('claude', 'Claude.exe'), ('codex', 'Codex.exe')]:
        target = setup.target.with_name(name)
        target.touch()
        path = setup.path.with_name(app_id + '.json')
        path.write_text(json.dumps(dict(setup.manifest, app_id=app_id, target=str(target))), encoding='utf-8')
        paths[app_id] = path
        registration.apply_registration(path, True)
        assert registration.read_registration(app_id)['target'] == str(target)
    assert len(setup.registry.data) == 6
    before = deepcopy(setup.registry.data)
    registration.apply_registration(paths['codex'], False)
    assert registration.read_registration('codex') is None
    for app_id in ('claude', 'grok-bot'):
        key = registration.registry_key(app_id)
        assert setup.registry.data[key] == before[key]
        assert setup.registry.data[key + '\\' + registration.FILTER] == before[key + '\\' + registration.FILTER]
    monkeypatch.setattr(registration, 'manifest_path', lambda app_id='grok-bot': paths[app_id])
    assert registration.uninstall() == 0
    assert setup.registry.data == {}


def test_register_rejects_msix_even_when_manually_selected_as_exe(setup):
    (setup.target.parent / 'AppxManifest.xml').write_text('<Package/>', encoding='utf-8')
    with pytest.raises(ValueError, match='MSIX'):
        registration.apply_registration(setup.path, True)
    assert setup.registry.data == {}


def test_register_rejects_versioned_squirrel_path(setup):
    target = setup.target.parent / 'app-1.2.3' / 'Claude.exe'
    target.parent.mkdir()
    target.touch()
    setup.path.write_text(json.dumps(dict(setup.manifest, app_id='claude', target=str(target))), encoding='utf-8')
    with pytest.raises(ValueError, match='版本'):
        registration.apply_registration(setup.path, True)
    assert setup.registry.data == {}
