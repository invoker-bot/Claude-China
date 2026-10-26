from unittest.mock import Mock
import os
from pathlib import Path
import re
import types
import threading

import pytest

from src.claude_china.desktop import config as cfg
from src.claude_china.desktop.bridge import LauncherBridge


def test_old_settings_default_to_system_without_overwriting_other_values(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, 'DESKTOP_CONFIG_FILE', tmp_path / 'desktop.yaml')
    cfg.save_desktop_config({'env_vars': {'MY_VALUE': '设置'}, 'favorite_directories': ['/projects/a']})
    data = cfg.load_desktop_config()
    assert cfg.get_language(data) == 'system'
    assert data['env_vars'] == {'MY_VALUE': '设置'}


@pytest.mark.parametrize('raw, expected', [
    ('zh_CN.UTF-8', 'zh-CN'), ('zh-SG', 'zh-CN'), ('zh-Hans-HK', 'zh-CN'),
    ('zh_HK', 'zh-TW'), ('zh-Hant', 'zh-TW'), ('zh-TW', 'zh-TW'),
    ('en_GB.UTF-8', 'en'), ('fr-FR', 'en'), ('C', 'en'), (None, 'en'),
])
def test_system_language_aliases_and_fallback(raw, expected, monkeypatch):
    from src.claude_china.desktop import localization
    monkeypatch.setattr(localization, 'system_language', lambda: raw)
    assert localization.resolve_language('system') == expected


def test_language_change_is_persisted_without_saving_another_settings_draft(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, 'DESKTOP_CONFIG_FILE', tmp_path / 'desktop.yaml')
    original = {'env_vars': {'HTTPS_PROXY': 'http://localhost:7890'},
                'safety_check': True, 'apps': {'codex': {'path': '/apps/codex'}},
                'terminal_favorites': ['/project']}
    cfg.save_desktop_config(original)
    bridge = LauncherBridge(Mock(), apps=[])
    bridge._language_changed = Mock()
    result = bridge.set_language('en')
    assert result['ok']
    assert result['data']['language'] == result['data']['resolved'] == 'en'
    assert result['data']['messages']['设置'] == 'Settings'
    saved = cfg.load_desktop_config()
    for key, value in original.items():
        assert saved[key] == value
    assert saved['language'] == 'en'
    bridge._language_changed.assert_called_once_with()
    assert LauncherBridge(Mock(), apps=[]).get_locale()['language'] == 'en'


@pytest.mark.parametrize('invalid', ['fr', '', '../en', None, [], True])
def test_invalid_language_does_not_change_disk(tmp_path, monkeypatch, invalid):
    monkeypatch.setattr(cfg, 'DESKTOP_CONFIG_FILE', tmp_path / 'desktop.yaml')
    cfg.save_desktop_config({'language': 'zh-TW'})
    bridge = LauncherBridge(Mock(), apps=[])
    before = cfg.DESKTOP_CONFIG_FILE.read_bytes()
    assert bridge.set_language(invalid)['ok'] is False
    assert cfg.DESKTOP_CONFIG_FILE.read_bytes() == before


def test_translation_preserves_dynamic_values_and_literal_braces():
    from src.claude_china.desktop.localization import translate
    assert translate('设置', 'en') == 'Settings'
    assert translate('设置', 'zh-TW') == '設定'
    assert translate('已发送 {0} 启动请求', 'en', '设置 {token}') == 'Launch requested for 设置 {token}'
    assert translate('Unknown operating system message', 'en') == 'Unknown operating system message'


def test_language_save_failure_keeps_selection_and_does_not_refresh_native_ui(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, 'DESKTOP_CONFIG_FILE', tmp_path / 'desktop.yaml')
    cfg.save_desktop_config({'language': 'zh-CN'})
    bridge = LauncherBridge(Mock(), apps=[])
    bridge._language_changed = Mock()
    monkeypatch.setattr(cfg, 'save_desktop_config', Mock(side_effect=OSError('disk full')))
    assert bridge.set_language('en')['ok'] is False
    assert bridge.get_locale()['language'] == 'zh-CN'
    bridge._language_changed.assert_not_called()


def test_catalogs_have_matching_keys_and_preserve_all_placeholders():
    from src.claude_china.desktop.localization import catalogs, NATIVE_MESSAGES
    data = catalogs()
    assert data['en'].keys() == data['zh-TW'].keys()
    assert set(NATIVE_MESSAGES.values()) <= data['en'].keys()
    for language, messages in data.items():
        for source, target in messages.items():
            assert target.strip(), (language, source)
            assert sorted(re.findall(r'\{\d+\}', source)) == sorted(re.findall(r'\{\d+\}', target)), (language, source)


def test_static_interface_has_translations():
    from html.parser import HTMLParser
    from src.claude_china.desktop.localization import catalogs
    messages = catalogs()['en']
    missing = set()

    def check(value):
        value = value.strip()
        if re.search('[\u4e00-\u9fff]', value) and value not in ('简体中文', '繁體中文') and value not in messages:
            missing.add(value)

    class Labels(HTMLParser):
        def handle_data(self, value):
            check(value)

        def handle_starttag(self, tag, attributes):
            for name, value in attributes:
                if name in ('title', 'aria-label', 'placeholder'):
                    check(value or '')

    Labels().feed((Path(__file__).parents[1] / 'src/claude_china/desktop/ui/index.html').read_text(encoding='utf-8'))
    assert not missing


def test_safety_panel_merges_webrtc_into_environment_check():
    from src.claude_china.desktop.localization import catalogs
    html = (Path(__file__).parents[1] / 'src/claude_china/desktop/ui/index.html').read_text(encoding='utf-8')
    panel = html[html.index('id="editor-safety"'):html.index('id="update-panel"')]
    assert panel.count('id="safety-check"') == 1
    assert 'id="safety-actions"' in panel
    assert '浏览器 WebRTC 出口' not in panel
    assert 'privacy-check' not in panel
    assert 'privacy-result' not in panel
    for language in ('en', 'zh-TW'):
        for label in ('检查环境', '修复环境', '还原环境', '检查通过', '允许启动'):
            assert label in catalogs()[language], (language, label)


def test_language_selection_never_changes_process_environment(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, 'DESKTOP_CONFIG_FILE', tmp_path / 'desktop.yaml')
    bridge = LauncherBridge(Mock(), apps=[])
    before = dict(os.environ)
    for language in ('en', 'zh-TW', 'zh-CN', 'system'):
        assert bridge.set_language(language)['ok']
    assert dict(os.environ) == before


def test_windows_uses_display_language_not_region(monkeypatch):
    import ctypes
    from src.claude_china.desktop import localization
    monkeypatch.setattr(localization, 'sys', types.SimpleNamespace(platform='win32'))
    monkeypatch.setattr(ctypes, 'windll', types.SimpleNamespace(
        kernel32=types.SimpleNamespace(GetUserDefaultUILanguage=lambda: 0x0404)), raising=False)
    monkeypatch.setenv('LANG', 'zh_CN.UTF-8')
    assert localization.resolve_language('system') == 'zh-TW'


def test_macos_uses_preferred_language(tmp_path, monkeypatch):
    import plistlib
    from src.claude_china.desktop import localization
    monkeypatch.setattr(localization, 'sys', types.SimpleNamespace(platform='darwin'))
    monkeypatch.setattr(localization.Path, 'home', lambda: tmp_path)
    preferences = tmp_path / 'Library/Preferences/.GlobalPreferences.plist'
    preferences.parent.mkdir(parents=True)
    preferences.write_bytes(plistlib.dumps({'AppleLanguages': ['zh-Hant-US', 'en']}))
    assert localization.resolve_language('system') == 'zh-TW'


def test_linux_language_environment_precedence(monkeypatch):
    from src.claude_china.desktop import localization
    monkeypatch.setattr(localization, 'sys', types.SimpleNamespace(platform='linux'))
    monkeypatch.setenv('LANG', 'en_US.UTF-8')
    monkeypatch.setenv('LANGUAGE', 'zh_TW:en')
    monkeypatch.setenv('LC_MESSAGES', 'zh_CN.UTF-8')
    monkeypatch.setenv('LC_ALL', 'en_GB.UTF-8')
    assert localization.resolve_language('system') == 'en'
    monkeypatch.delenv('LC_ALL')
    assert localization.resolve_language('system') == 'zh-CN'
    monkeypatch.delenv('LC_MESSAGES')
    assert localization.resolve_language('system') == 'zh-TW'


def test_language_change_during_safety_check_does_not_cancel_app_launch(tmp_path, monkeypatch):
    from src.claude_china.desktop.apps import APP_REGISTRY
    from src.claude_china.desktop.platforms.base import AppStatus
    monkeypatch.setattr(cfg, 'DESKTOP_CONFIG_FILE', tmp_path / 'desktop.yaml')
    backend = Mock()
    backend.detect.side_effect = lambda app, path: AppStatus(app.id, found=True, direct=True, launch_target='fixture', match_root='fixture')
    bridge = LauncherBridge(backend, APP_REGISTRY, base_env={})

    def check(*args):
        assert bridge.set_language('en')['ok']
        return {'allowed': True, 'status': 'supported'}

    monkeypatch.setattr(bridge, '_check_safety', check)
    assert bridge.launch_app('grok-bot')['ok']
    backend.launch.assert_called_once()


def test_native_diagnostic_translates_nested_reason_but_keeps_user_data(tmp_path, monkeypatch):
    from src.claude_china.desktop.localization import display_message
    monkeypatch.setattr(cfg, 'DESKTOP_CONFIG_FILE', tmp_path / 'desktop.yaml')
    cfg.save_desktop_config({'language': 'en'})
    assert display_message('安全检查未通过：出口位于统一禁止地区：中国大陆，禁止启动。 已取消启动。') == (
        'Safety check failed: The exit region is blocked by the shared policy: Mainland China. Launch is blocked. Launch cancelled.')
    assert display_message('已发送 设置 {0} 启动请求') == 'Launch requested for 设置 {0}'
    monkeypatch.setattr(cfg, 'load_desktop_config', Mock(side_effect=OSError('fixture')))
    assert display_message('original diagnostic') == 'original diagnostic'


def test_concurrent_language_and_settings_saves_preserve_both(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, 'DESKTOP_CONFIG_FILE', tmp_path / 'desktop.yaml')
    bridge = LauncherBridge(Mock(), apps=[])
    read_language, read_settings, resume = threading.Event(), threading.Event(), threading.Event()
    original_load = cfg.load_desktop_config
    results = []

    def load():
        data = original_load()
        if threading.current_thread().name == 'language-save':
            read_language.set()
            assert resume.wait(5)
        elif threading.current_thread().name == 'settings-save':
            read_settings.set()
        return data

    monkeypatch.setattr(cfg, 'load_desktop_config', load)
    language = threading.Thread(name='language-save', target=lambda: results.append(bridge.set_language('en')))
    settings = threading.Thread(name='settings-save', target=lambda: results.append(
        bridge.save_settings({'env_vars': {'TEST': 'new-value'}})))
    language.start()
    try:
        assert read_language.wait(5)
        settings.start()
        # Without a transaction the second writer reads the stale preferences.
        read_settings.wait(0.1)
    finally:
        resume.set()
        language.join(5)
        settings.join(5)
    assert not language.is_alive() and not settings.is_alive()
    assert len(results) == 2 and all(result['ok'] for result in results)
    saved = original_load()
    assert saved['language'] == 'en'
    assert saved['env_vars'] == {'TEST': 'new-value'}


def test_failed_language_write_keeps_original_file_bytes(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, 'DESKTOP_CONFIG_FILE', tmp_path / 'desktop.yaml')
    cfg.save_desktop_config({'language': 'zh-CN', 'env_vars': {'KEEP': 'fixture'}})
    bridge = LauncherBridge(Mock(), apps=[])
    original = cfg.DESKTOP_CONFIG_FILE.read_bytes()

    def disk_full(data, stream, **kwargs):
        stream.write('partial: ')
        raise OSError('disk full')

    monkeypatch.setattr(cfg.yaml, 'dump', disk_full)
    assert not bridge.set_language('en')['ok']
    assert cfg.DESKTOP_CONFIG_FILE.read_bytes() == original
    assert not list(tmp_path.glob('.desktop-*.tmp'))
