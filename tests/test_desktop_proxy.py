from unittest.mock import Mock

import pytest

from src.claude_china.desktop.platforms import linux, macos, windows


@pytest.mark.parametrize("value, expected", [
    ("127.0.0.1:7890", "http://127.0.0.1:7890"),
    (" http://LOCALHOST:8080/ ", "http://localhost:8080"),
    ("proxy.example.com", "http://proxy.example.com:80"),
    ("[::1]:7890", "http://[::1]:7890"),
    ("http://user:p%40ss@proxy.example:3128", "http://user:p%40ss@proxy.example:3128"),
])
def test_http_proxy_normalization(value, expected):
    from src.claude_china.desktop.proxy import http_proxy_url

    assert http_proxy_url(value) == expected


@pytest.mark.parametrize("value", [
    None, "", "http://", "localhost:", "localhost:0", "localhost:65536",
    "localhost:abc", "localhost:-1", "socks5://localhost:1080",
    "https://localhost:7890", "file:///proxy.pac", "http://localhost/proxy.pac",
    "http://localhost:7890?x=1", "http://localhost:7890#frag",
    "http://local host:7890", "http://local\nhost:7890", "localhost:7890\0",
    "http://[::1", "::1:7890", "http://localhost:7890\\other",
    "http://user:secret@@localhost:7890", "http://user:p%zz@localhost:7890",
])
def test_invalid_http_proxy_is_rejected_without_echoing_credentials(value):
    from src.claude_china.desktop.proxy import SystemProxyError, http_proxy_url

    with pytest.raises(SystemProxyError) as error:
        http_proxy_url(value)
    assert "secret" not in str(error.value)


def registry(monkeypatch, values):
    fake = Mock(HKEY_CURRENT_USER="HKCU")

    def read(key, name):
        if name not in values:
            raise FileNotFoundError(name)
        return values[name], 1

    fake.QueryValueEx.side_effect = read
    monkeypatch.setattr(windows, "winreg", fake)
    return fake


@pytest.mark.parametrize("server", [
    "127.0.0.1:7890", "http://127.0.0.1:7890",
    "http=127.0.0.1:7890;https=localhost:9999;socks=localhost:1080",
    "HTTPS=localhost:9999 HTTP=127.0.0.1:7890",
    "http=127.0.0.1:7890;", "https=localhost:9999;127.0.0.1:7890",
])
def test_windows_selects_system_http_endpoint_for_both_protocols(monkeypatch, server):
    fake = registry(monkeypatch, {"ProxyEnable": 1, "ProxyServer": server})
    assert windows.WindowsBackend().system_http_proxy() == "http://127.0.0.1:7890"
    fake.CloseKey.assert_called_once_with(fake.OpenKey.return_value)


@pytest.mark.parametrize("values", [
    {"ProxyEnable": 0, "ProxyServer": "localhost:7890"},
    {"ProxyEnable": 1},
    {"ProxyEnable": 1, "ProxyServer": "http=localhost:abc;https=localhost:7890"},
    {"ProxyEnable": 1, "ProxyServer": "socks=localhost:1080"},
    {"ProxyEnable": 1, "ProxyServer": "https=localhost:7890"},
    {"ProxyEnable": 1, "ProxyServer": "http=localhost:7890;http=localhost:9999"},
    {"ProxyEnable": 1, "ProxyServer": "localhost:7890;localhost:9999"},
    {"AutoConfigURL": "https://example.com/proxy.pac"},
])
def test_windows_invalid_or_pac_only_proxy_fails_and_closes_registry(monkeypatch, values):
    from src.claude_china.desktop.proxy import SystemProxyError

    fake = registry(monkeypatch, values)
    with pytest.raises(SystemProxyError):
        windows.WindowsBackend().system_http_proxy()
    fake.CloseKey.assert_called_once_with(fake.OpenKey.return_value)


def test_windows_registry_failure_is_not_a_direct_connection(monkeypatch):
    from src.claude_china.desktop.proxy import SystemProxyError

    fake = registry(monkeypatch, {})
    fake.OpenKey.side_effect = PermissionError("unreadable registry")
    with pytest.raises(SystemProxyError):
        windows.WindowsBackend().system_http_proxy()


def test_macos_reads_global_http_proxy_and_ignores_scoped_overrides(monkeypatch):
    text = """<dictionary> {
  HTTPEnable : 1
  HTTPProxy : ::1
  HTTPPort : 7890
  HTTPSProxy : localhost
  HTTPSPort : 9999
  __SCOPED__ : <dictionary> {
    en0 : <dictionary> {
      HTTPEnable : 0
      HTTPProxy : other
      HTTPPort : 8080
    }
  }
}"""
    backend = macos.MacBackend()
    monkeypatch.setattr(backend, "_scutil_output", lambda: text)
    assert backend.system_http_proxy() == "http://[::1]:7890"


@pytest.mark.parametrize("text", [
    "", "HTTPSEnable : 1\nHTTPSProxy : localhost\nHTTPSPort : 7890",
    "HTTPEnable : 0\nHTTPProxy : localhost\nHTTPPort : 7890",
    "HTTPEnable : 1\nHTTPProxy : localhost\nHTTPPort : 0",
    "HTTPEnable : 1\nHTTPProxy : localhost",
    "HTTPEnable : 1\nHTTPProxy : http://localhost\nHTTPPort : 7890",
    "HTTPEnable : 1\nHTTPProxy : [[localhost]]\nHTTPPort : 7890",
    "ProxyAutoConfigEnable : 1\nProxyAutoConfigURLString : https://example.com/proxy.pac",
    "<dictionary> {\n  __SCOPED__ : <dictionary> {\n    HTTPEnable : 1\n    HTTPProxy : localhost\n    HTTPPort : 7890\n  }\n}",
])
def test_macos_requires_enabled_global_static_http_proxy(monkeypatch, text):
    from src.claude_china.desktop.proxy import SystemProxyError

    backend = macos.MacBackend()
    monkeypatch.setattr(backend, "_scutil_output", lambda: text)
    with pytest.raises(SystemProxyError):
        backend.system_http_proxy()


@pytest.fixture
def linux_proxy(monkeypatch):
    for key in ("http_proxy", "https_proxy", "all_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
        monkeypatch.delenv(key, raising=False)
    values = {"mode": "'manual'", "host": "'127.0.0.1'", "port": "7890",
              "use-authentication": "false"}
    monkeypatch.setattr(linux.subprocess, "check_output", lambda argv, **kw: values[argv[-1]])
    return values


def test_linux_reads_manual_gnome_http_proxy(linux_proxy):
    assert linux.LinuxBackend().system_http_proxy() == "http://127.0.0.1:7890"


def test_linux_prefers_http_environment_and_lowercase_variant(linux_proxy, monkeypatch):
    monkeypatch.setenv("HTTP_PROXY", "http://localhost:8080")
    monkeypatch.setenv("http_proxy", "http://localhost:8888")
    assert linux.LinuxBackend().system_http_proxy() == "http://localhost:8888"


def test_linux_invalid_environment_does_not_fall_back_to_gnome(linux_proxy, monkeypatch):
    from src.claude_china.desktop.proxy import SystemProxyError

    monkeypatch.setenv("http_proxy", "socks5://localhost:1080")
    with pytest.raises(SystemProxyError):
        linux.LinuxBackend().system_http_proxy()


@pytest.mark.parametrize("key,value", [
    ("mode", "'none'"), ("mode", "'auto'"), ("host", "''"),
    ("host", "'http://localhost'"), ("port", "0"), ("port", "65536"),
    ("use-authentication", "true"),
])
def test_linux_unsupported_gnome_configuration_fails(linux_proxy, key, value):
    from src.claude_china.desktop.proxy import SystemProxyError

    linux_proxy[key] = value
    with pytest.raises(SystemProxyError):
        linux.LinuxBackend().system_http_proxy()


def test_linux_missing_settings_service_fails(linux_proxy, monkeypatch):
    from src.claude_china.desktop.proxy import SystemProxyError

    monkeypatch.setattr(linux.subprocess, "check_output", Mock(side_effect=FileNotFoundError))
    with pytest.raises(SystemProxyError):
        linux.LinuxBackend().system_http_proxy()
