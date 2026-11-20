from io import BytesIO
import json
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.claude_china.desktop import app_install


def html(*links):
    return ''.join(f'<a href="{link}">Download</a>' for link in links)


def test_claude_selects_current_desktop_installer_not_science_or_untrusted_host():
    page = html(
        'https://claude.ai/api/desktop/darwin/universal/dmg/latest/redirect',
        'https://claude.ai/api/desktop/win32/x64/setup/latest/redirect',
        'https://claude.ai/api/desktop/win32/arm64/setup/latest/redirect',
        'https://downloads.claude.ai/claude-science/latest/windows-x64.exe',
        'https://evil.example.test/claude.exe',
    )
    plan = app_install.select_plan('claude', page, 'https://claude.com/download', 'win32', 'x86_64')
    assert plan.method == 'store-link' and plan.url.endswith('9P6K58THS811')
    mac = app_install.select_plan('claude', page, 'https://claude.com/download', 'darwin', 'arm64')
    assert 'darwin/universal' in mac.url
    linux = app_install.select_plan('claude', page, 'https://claude.com/download', 'linux', 'x86_64')
    assert linux.method == 'page' and linux.url == 'https://claude.com/download'


def test_codex_uses_store_on_windows_and_current_chatgpt_packages_elsewhere():
    page = html(
        'https://get.microsoft.com/installer/download/9PLM9XGG6VKS?cid=website',
        'https://persistent.oaistatic.com/codex-app-prod/ChatGPT.dmg',
        'https://persistent.oaistatic.com/codex-app-prod/linux/deb/latest/chatgpt_amd64.deb',
        'https://persistent.oaistatic.com/codex-app-prod/linux/deb/latest/chatgpt_arm64.deb',
        'https://persistent.oaistatic.com/codex-app-prod/linux/rpm/latest/chatgpt.x86_64.rpm',
    )
    windows = app_install.select_plan('codex', page, 'https://chatgpt.com/codex/', 'win32', 'x86_64')
    assert windows.method == 'store' and windows.filename == 'Codex-Store-Setup.exe'
    mac = app_install.select_plan('codex', page, 'https://chatgpt.com/codex/', 'darwin', 'arm64')
    assert mac.filename == 'ChatGPT.dmg'
    deb = app_install.select_plan('codex', page, 'https://chatgpt.com/codex/', 'linux', 'x86_64', 'deb')
    rpm = app_install.select_plan('codex', page, 'https://chatgpt.com/codex/', 'linux', 'x86_64', 'rpm')
    assert deb.filename == 'chatgpt_amd64.deb' and rpm.filename == 'chatgpt.x86_64.rpm'
    arm = app_install.select_plan('codex', page, 'https://chatgpt.com/codex/', 'linux', 'aarch64', 'deb')
    assert arm.filename == 'chatgpt_arm64.deb'


@pytest.mark.parametrize('machine,expected', [('x86_64', 'win32-x64'), ('arm64', 'win32-arm64')])
def test_grok_bot_selects_windows_architecture(machine, expected):
    page = html(
        'https://downloads.cursor.com/grokbot/stable/win32-x64/1.2.3/Grok_Bot_Setup.exe',
        'https://downloads.cursor.com/grokbot/stable/win32-arm64/1.2.3/Grok_Bot_Setup.exe',
    )
    plan = app_install.select_plan('grok-bot', page, 'https://cursor.com/download/bot', 'win32', machine)
    assert expected in plan.url and plan.filename == 'Grok_Bot_Setup.exe'


def test_antigravity_selects_hub_not_ide_and_marks_linux_archive():
    page = html(
        'https://storage.googleapis.com/antigravity-public/antigravity-hub/2.33/windows-x64/Antigravity-x64.exe',
        'https://storage.googleapis.com/antigravity-public/antigravity-hub/2.33/darwin-arm/Antigravity.dmg',
        'https://storage.googleapis.com/antigravity-public/antigravity-hub/2.33/linux-x64/Antigravity.tar.gz',
        'https://storage.googleapis.com/antigravity-public/antigravity/stable/2.8/windows-x64/Antigravity%20IDE.exe',
    )
    windows = app_install.select_plan('antigravity', page, 'https://antigravity.google/download/', 'win32', 'x86_64')
    mac = app_install.select_plan('antigravity', page, 'https://antigravity.google/download/', 'darwin', 'arm64')
    linux = app_install.select_plan('antigravity', page, 'https://antigravity.google/download/', 'linux', 'x86_64')
    assert 'antigravity-hub' in windows.url and 'IDE' not in windows.filename
    assert 'darwin-arm' in mac.url
    assert linux.method == 'archive' and linux.filename == 'Antigravity.tar.gz'


class Response:
    def __init__(self, data, length=None):
        self.stream = BytesIO(data)
        self.headers = {'Content-Length': str(len(data) if length is None else length)}
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def read(self, size): return self.stream.read(size)


def test_download_publishes_complete_file_and_supports_cancellation(tmp_path, monkeypatch):
    plan = app_install.InstallPlan('claude', 'https://downloads.claude.ai/claude.exe', 'Claude.exe', 'package')
    monkeypatch.setattr(app_install, '_open', lambda url, spec: Response(b'official-installer'))
    progress = []
    path, digest = app_install.download(plan, tmp_path / 'one', threading.Event(),
                                        lambda done, total: progress.append((done, total)))
    assert path.read_bytes() == b'official-installer' and len(digest) == 64
    assert progress[-1] == (18, 18) and not list(path.parent.glob('*.part'))

    cancelled = threading.Event()
    monkeypatch.setattr(app_install, '_open', lambda url, spec: Response(b'abc'))
    with pytest.raises(app_install.InstallCancelled):
        app_install.download(plan, tmp_path / 'two', cancelled,
                             lambda done, total: cancelled.set())
    assert not list((tmp_path / 'two').glob('*.part'))


def test_download_rejects_excessive_declared_size(tmp_path, monkeypatch):
    plan = app_install.InstallPlan('claude', 'https://downloads.claude.ai/claude.exe', 'Claude.exe', 'package')
    monkeypatch.setattr(app_install, '_open', lambda url, spec: Response(b'abc', app_install.MAX_DOWNLOAD + 1))
    with pytest.raises(app_install.InstallError, match='大小'):
        app_install.download(plan, tmp_path, threading.Event(), lambda done, total: None)


@pytest.mark.parametrize('status,subject,ok', [
    ('Valid', 'CN=Anthropic, PBC', True),
    ('Valid', 'CN=Evil Publisher', False),
    ('NotSigned', 'CN=Anthropic, PBC', False),
])
def test_windows_signature_requires_valid_status_and_publisher(monkeypatch, status, subject, ok):
    result = SimpleNamespace(returncode=0, stdout=json.dumps({'Status': status, 'Subject': subject}))
    monkeypatch.setattr(app_install.subprocess, 'run', lambda *args, **kwargs: result)
    if ok:
        app_install.verify_windows_signature('fixture.exe', ('Anthropic',))
    else:
        with pytest.raises(app_install.InstallError):
            app_install.verify_windows_signature('fixture.exe', ('Anthropic',))


def test_manager_opens_official_page_when_no_direct_package(monkeypatch, tmp_path):
    manager = app_install.AppInstallManager(tmp_path)
    plan = app_install.InstallPlan('claude', 'https://claude.com/download', '', 'page')
    monkeypatch.setattr(app_install, 'resolve_plan', lambda app_id: plan)
    opened = Mock()
    monkeypatch.setattr('webbrowser.open', opened)
    manager.start('claude', lambda: False)
    for _ in range(50):
        if manager.status('claude')['phase'] == 'launched': break
        threading.Event().wait(.02)
    assert manager.status('claude')['method'] == 'page'
    opened.assert_called_once_with('https://claude.com/download')


def test_embedded_official_store_url_is_discovered():
    page = '<script>window.installer="https://get.microsoft.com/installer/download/9PLM9XGG6VKS?cid=website";</script>'
    plan = app_install.select_plan('codex', page, 'https://chatgpt.com/codex/', 'win32', 'x86_64')
    assert plan.method == 'store' and 'get.microsoft.com' in plan.url


def test_direct_http_rejection_falls_back_to_official_page(tmp_path, monkeypatch):
    manager = app_install.AppInstallManager(tmp_path)
    plan = app_install.InstallPlan('claude', 'https://claude.ai/api/desktop/install', 'Claude.dmg', 'package')
    monkeypatch.setattr(app_install, 'resolve_plan', lambda app_id: plan)
    error = app_install.urllib.error.HTTPError(plan.url, 403, 'Forbidden', {}, None)
    monkeypatch.setattr(app_install, 'download', Mock(side_effect=error))
    opened = Mock()
    monkeypatch.setattr('webbrowser.open', opened)
    manager.start('claude', lambda: False)
    for _ in range(50):
        if manager.status('claude')['phase'] == 'launched': break
        threading.Event().wait(.02)
    assert manager.status('claude')['method'] == 'page'
    opened.assert_called_once_with('https://claude.com/download')
