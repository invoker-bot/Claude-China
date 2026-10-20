from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.claude_china.desktop.platforms import windows, macos, linux
from src.claude_china.desktop.proxy import SystemProxyError
from src.claude_china.desktop import safety_local, safety
from src.claude_china.desktop.platforms.base import AppStatus


def windows_settings(monkeypatch, values):
    def query(key, name):
        if name not in values:
            raise FileNotFoundError(name)
        return values[name], 1
    registry = SimpleNamespace(HKEY_CURRENT_USER=1, OpenKey=Mock(return_value=2),
                               QueryValueEx=query, CloseKey=Mock())
    monkeypatch.setattr(windows, "winreg", registry)
    return registry


def test_windows_safety_probes_https_proxy_not_http_port(monkeypatch):
    registry = windows_settings(monkeypatch, {"ProxyEnable": 1,
        "ProxyServer": "http=localhost:8080;https=localhost:8443", "ProxyOverride": "<local>"})
    result = windows.WindowsBackend().safety_proxy()
    assert result == {"proxy": "http://localhost:8443", "bypass": "<local>"}
    registry.CloseKey.assert_called_once()


@pytest.mark.parametrize("extra", [{"AutoConfigURL": "https://proxy.example/pac"}, {"AutoDetect": 1}])
def test_windows_pac_and_autodetection_are_unknown(monkeypatch, extra):
    registry = windows_settings(monkeypatch, {"ProxyEnable": 0, **extra})
    with pytest.raises(SystemProxyError):
        windows.WindowsBackend().safety_proxy()
    registry.CloseKey.assert_called_once()


def test_windows_disabled_stale_proxy_is_not_used(monkeypatch):
    windows_settings(monkeypatch, {"ProxyEnable": 0, "ProxyServer": "old:123"})
    assert windows.WindowsBackend().safety_proxy() == {"proxy": None}


def test_mac_reads_https_and_preserves_bypass(monkeypatch):
    backend = macos.MacBackend()
    monkeypatch.setattr(backend, "_scutil_output", lambda: """<dictionary> {
  HTTPEnable : 1
  HTTPProxy : localhost
  HTTPPort : 8080
  HTTPSEnable : 1
  HTTPSProxy : localhost
  HTTPSPort : 8443
  ExceptionsList : <array> {
    0 : localhost
    1 : *.example.com
  }
}""")
    assert backend.safety_proxy() == {"proxy": "http://localhost:8443", "bypass": "localhost,*.example.com"}


@pytest.mark.parametrize("name", ["ProxyAutoConfigEnable", "ProxyAutoDiscoveryEnable", "SOCKSEnable"])
def test_mac_automatic_or_socks_routes_are_unknown(monkeypatch, name):
    backend = macos.MacBackend()
    monkeypatch.setattr(backend, "_scutil_output", lambda: "<dictionary> {\n  " + name + " : 1\n}")
    with pytest.raises(SystemProxyError):
        backend.safety_proxy()


def test_mac_empty_settings_are_unknown_but_empty_dictionary_is_direct(monkeypatch):
    backend = macos.MacBackend()
    monkeypatch.setattr(backend, "_scutil_output", lambda: "")
    with pytest.raises(SystemProxyError):
        backend.safety_proxy()
    monkeypatch.setattr(backend, "_scutil_output", lambda: "<dictionary> {\n}")
    assert backend.safety_proxy() == {"proxy": None, "bypass": ""}


@pytest.mark.parametrize("same,expected", [(True, 8080), (False, 8443)])
def test_linux_respects_same_proxy_and_https_settings(monkeypatch, same, expected):
    values = {("mode", ""): "'manual'", ("use-same-proxy", ""): str(same).lower(),
              ("host", "http"): "'localhost'", ("host", "https"): "'localhost'",
              ("port", "http"): "8080", ("port", "https"): "8443",
              ("use-authentication", "http"): "false", ("ignore-hosts", ""): "['localhost']"}
    backend = linux.LinuxBackend()
    monkeypatch.setattr(backend, "_proxy_setting", lambda name, protocol="": values[(name, protocol)])
    assert backend.safety_proxy() == {"proxy": f"http://localhost:{expected}", "bypass": "localhost"}


def test_linux_without_gnome_keeps_environment_route(monkeypatch):
    backend = linux.LinuxBackend()
    monkeypatch.setattr(backend, "_proxy_setting", Mock(side_effect=FileNotFoundError()))
    result = safety.select_route({"HTTPS_PROXY": "http://localhost:7890"}, backend, AppStatus("claude", True, True))
    assert result["proxy"] == "http://localhost:7890"


def test_changed_system_route_cancels_probe(monkeypatch):
    backend = Mock()
    backend.safety_proxy.side_effect = [{"proxy": "http://localhost:7890"}, {"proxy": "http://localhost:7891"}]
    monkeypatch.setattr(safety, "lookup_ip", lambda proxy: {"country_code": "US", "ip": "1.1.1.1"})
    result = safety.inspect_environment("claude", {}, backend, AppStatus("claude", True, True))
    assert result["status"] == "unknown"
    assert "变化" in result["reason"]


def test_windows_metadata_keeps_display_language_independent_of_region(monkeypatch):
    kernel = SimpleNamespace(GetUserGeoID=lambda kind: 1, GetUserDefaultUILanguage=lambda: 0x0804,
        GetUserDefaultLocaleName=lambda buf, length: setattr(buf, "value", "en-US"),
        GetGeoInfoW=lambda geo, kind, buf, length, lang: setattr(buf, "value", "SG"))
    monkeypatch.setattr(safety_local.ctypes, "windll", SimpleNamespace(kernel32=kernel), raising=False)
    assert safety_local._windows_locale() == ("zh-CN", "SG")


def test_linux_locale_uses_precedence_without_changing_process_locale(monkeypatch):
    monkeypatch.setattr(safety_local, "sys", SimpleNamespace(platform="linux"))
    monkeypatch.setenv("LC_ALL", "zh_CN.UTF-8")
    monkeypatch.setenv("LANG", "en_US.UTF-8")
    result = safety_local.local_environment()
    assert result["language"] == "zh-CN"
    assert result["region"] == "CN"
