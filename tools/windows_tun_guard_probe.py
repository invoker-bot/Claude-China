"""Isolated TUN/WebRTC acceptance: two disposable Wintun NICs, no default routes.

Requires an elevated Python and the official signed Wintun 0.14.1 DLL. Only
documentation/benchmark address ranges are routed. Existing adapters and their
configuration are never changed. Both test NICs are removed in finally.
"""

import argparse
import ctypes as C
import ipaddress
import json
import os
from pathlib import Path
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from claude_china.desktop.platforms.windows_wfp import Engine, GUID, U32, U64, PTR
from claude_china.desktop.platforms.windows_tun import interface
from windows_network_guard_probe import SOURCE

RTC = r'''async url => {
  const pc = new RTCPeerConnection({iceServers:[{urls:url}]});
  pc.createDataChannel('probe');
  const found = [];
  pc.onicecandidate = event => { if (event.candidate?.type === 'srflx') found.push(event.candidate.address); };
  await pc.setLocalDescription(await pc.createOffer());
  await new Promise(resolve => {
    const timer = setTimeout(resolve, 2500);
    pc.onicegatheringstatechange = () => { if(pc.iceGatheringState === 'complete'){clearTimeout(timer);resolve();} };
  });
  pc.close(); return found.filter(address => address.startsWith('203.0.113.'));
}'''


def ps(source):
    return subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command",
                           "$ErrorActionPreference='Stop'; " + source], check=True,
                          capture_output=True, text=True, timeout=30,
                          creationflags=subprocess.CREATE_NO_WINDOW).stdout


def checksum(data):
    data += b"\0" * (len(data) % 2)
    total = sum(struct.unpack("!%dH" % (len(data) // 2), data))
    while total >> 16:
        total = (total & 0xffff) + (total >> 16)
    return (~total) & 0xffff


class Tunnel:
    def __init__(self, dll, tag, subnet):
        self.dll, self.adapter, self.session = dll, None, None
        self.closed = threading.Event()
        self.thread = None
        self.received = 0
        self.tcp_received = 0
        self.debug = []
        self.name = "ClaudeChinaProbe-" + tag + "-" + uuid.uuid4().hex[:6]
        self.addresses = ["198.18.%d.1" % subnet, "2001:db8:%x::1" % subnet]
        self.peers = ["198.18.%d.2" % subnet, "2001:db8:%x::2" % subnet]
        self.mapped = "203.0.113.%d" % subnet
        self.adapter = dll.WintunCreateAdapter(self.name, "Wintun", None)
        if not self.adapter:
            raise C.WinError()
        luid = U64()
        dll.WintunGetAdapterLUID(self.adapter, C.byref(luid))
        api = C.WinDLL("iphlpapi")
        api.ConvertInterfaceLuidToGuid.argtypes = [C.POINTER(U64), C.POINTER(GUID)]
        guid = GUID()
        assert not api.ConvertInterfaceLuidToGuid(C.byref(luid), C.byref(guid))
        self.record = interface(str(guid))
        self.record["addresses"] = self.addresses
        self.record.pop("up")
        index = self.record["index"]
        ps("Set-NetIPInterface -InterfaceIndex %d -AddressFamily IPv6 -DadTransmits 0; " % index +
           "New-NetIPAddress -InterfaceIndex %d -IPAddress '%s' -PrefixLength 30 -PolicyStore ActiveStore | Out-Null; " % (index, self.addresses[0]) +
           "New-NetIPAddress -InterfaceIndex %d -IPAddress '%s' -PrefixLength 64 -PolicyStore ActiveStore | Out-Null; " % (index, self.addresses[1]) +
           "Set-NetIPInterface -InterfaceIndex %d -WeakHostSend Enabled -WeakHostReceive Enabled" % index)
        self.session = dll.WintunStartSession(self.adapter, 0x200000)
        if not self.session:
            raise C.WinError()
        self.thread = threading.Thread(target=self.pump, daemon=True)
        self.thread.start()
        ps("$limit=(Get-Date).AddSeconds(12); do { $ready=@(Get-NetIPAddress -InterfaceIndex %d | Where-Object { $_.IPAddress -in @('%s','%s') -and $_.AddressState -eq 'Preferred' }); if($ready.Count -eq 2){break}; Start-Sleep -Milliseconds 100 } while((Get-Date) -lt $limit); if($ready.Count -ne 2){throw 'Test adapter addresses not ready'}" % (index, *self.addresses))

    def pump(self):
        while not self.closed.is_set():
            size = U32()
            pointer = self.dll.WintunReceivePacket(self.session, C.byref(size))
            if not pointer:
                self.closed.wait(.005)
                continue
            packet = C.string_at(pointer, size.value)
            self.dll.WintunReleaseReceivePacket(self.session, pointer)
            try:
                response = self.respond(packet)
            except Exception as error:
                self.debug.append(repr(error))
                continue
            if response:
                output = self.dll.WintunAllocateSendPacket(self.session, len(response))
                if output:
                    C.memmove(output, response, len(response))
                    self.dll.WintunSendPacket(self.session, output)

    def respond(self, packet):
        version = packet[0] >> 4
        header = (packet[0] & 15) * 4 if version == 4 else 40
        protocol = packet[9] if version == 4 else packet[6]
        if protocol not in (6, 17) or len(packet) < header + (20 if protocol == 6 else 8):
            return None
        source = packet[12:16] if version == 4 else packet[8:24]
        destination = packet[16:20] if version == 4 else packet[24:40]
        sport, dport = struct.unpack("!HH", packet[header:header + 4])
        if dport not in (3478, 8080):
            return None
        if protocol == 6:
            self.tcp_received += 1
            seq, ack = struct.unpack("!II", packet[header + 4:header + 12])
            flags = packet[header + 13]
            body = packet[header + (packet[header + 12] >> 4) * 4:]
            if flags & 2:
                seq, ack, flags, body = 1000, seq + 1, 0x12, b""
            elif body:
                seq, ack, flags = 1001, seq + len(body), 0x19
                body = b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nContent-Length: 6\r\nConnection: close\r\n\r\ntun-ok"
            elif flags & 1:
                seq, ack, flags, body = ack, seq + 1, 0x10, b""
            else:
                return None
            segment = struct.pack("!HHIIBBHHH", dport, sport, seq, ack, 5 << 4, flags, 65535, 0, 0) + body
            position = 16
        else:
            self.received += 1
            body = packet[header + 8:]
            if len(body) >= 20 and body[:2] == b"\0\1" and body[4:8] == bytes.fromhex("2112a442"):
                mapped = int(ipaddress.IPv4Address(self.mapped)) ^ 0x2112a442
                attr = struct.pack("!HHBBHI", 0x20, 8, 0, 1, sport ^ 0x2112, mapped)
                body = struct.pack("!HH", 0x101, len(attr)) + body[4:20] + attr
            segment = struct.pack("!HHHH", dport, sport, len(body) + 8, 0) + body
            position = 6
        length = len(segment)
        pseudo = (destination + source + (struct.pack("!BBH", 0, protocol, length) if version == 4
                                         else struct.pack("!I3xB", length, protocol)))
        udp = segment[:position] + struct.pack("!H", checksum(pseudo + segment) or 0xffff) + segment[position + 2:]
        if version == 4:
            ip = struct.pack("!BBHHHBBH", 0x45, 0, len(udp) + 20, 0, 0, 64, protocol, 0) + destination + source
            ip = ip[:10] + struct.pack("!H", checksum(ip)) + ip[12:]
        else:
            ip = struct.pack("!IHBB", 6 << 28, len(udp), protocol, 64) + destination + source
        return ip + udp

    def close(self):
        self.closed.set()
        if self.thread:
            self.thread.join(2)
        if self.session:
            self.dll.WintunEndSession(self.session)
            self.session = None
        if self.adapter:
            self.dll.WintunCloseAdapter(self.adapter)
            self.adapter = None


def load(path):
    dll = C.WinDLL(str(path), use_last_error=True)
    functions = {
        "WintunCreateAdapter": ([C.c_wchar_p, C.c_wchar_p, C.POINTER(GUID)], PTR),
        "WintunCloseAdapter": ([PTR], None), "WintunGetAdapterLUID": ([PTR, C.POINTER(U64)], None),
        "WintunStartSession": ([PTR, U32], PTR), "WintunEndSession": ([PTR], None),
        "WintunReceivePacket": ([PTR, C.POINTER(U32)], PTR),
        "WintunReleaseReceivePacket": ([PTR, PTR], None),
        "WintunAllocateSendPacket": ([PTR, U32], PTR), "WintunSendPacket": ([PTR, PTR], None),
    }
    for name, (arguments, result) in functions.items():
        getattr(dll, name).argtypes, getattr(dll, name).restype = arguments, result
    return dll


def run(dll_path, report):
    tunnels, cases = [], []
    scope = "tun-probe-" + uuid.uuid4().hex
    owner = None
    held = []
    workspace = tempfile.TemporaryDirectory(prefix="claudec-tun-client-")
    try:
        assert C.windll.shell32.IsUserAnAdmin(), "Run elevated"
        dll = load(dll_path)
        first = Tunnel(dll, "A", 44)
        tunnels.append(first)
        second = Tunnel(dll, "B", 45)
        tunnels.append(second)
        folder = Path(workspace.name)
        source, executable = folder / "Probe.cs", folder / "Probe.exe"
        source.write_text(SOURCE, encoding="utf-8")
        compiler = Path(os.environ["WINDIR"]) / "Microsoft.NET/Framework64/v4.0.30319/csc.exe"
        subprocess.run([str(compiler), "/nologo", "/out:" + str(executable), str(source)], check=True, capture_output=True)
        def probe(label, address, allowed, mode="udp"):
            result = subprocess.run([str(executable), mode, address, "3478"], capture_output=True,
                                    text=True, timeout=5, creationflags=subprocess.CREATE_NO_WINDOW)
            assert (result.stdout == "ok") == allowed, (label, result.stdout, result.stderr)
            cases.append({"case": label, "result": result.stdout})
        time.sleep(1)
        probe("unprotected-tunnel-v4", first.peers[0], True)
        probe("unprotected-tunnel-v6", first.peers[1], True)
        for address in first.peers:
            process = subprocess.Popen([str(executable), "hold-udp", address, "3478"],
                                       stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                       text=True, creationflags=subprocess.CREATE_NO_WINDOW)
            held.append(process)
            assert process.stdout.readline().strip() == "ready"
        from playwright.sync_api import sync_playwright
        with sync_playwright() as runtime:
            original = Path(runtime.chromium.executable_path)
        browser_dir = folder / "browser"
        shutil.copytree(original.parent, browser_dir)
        browser_exe = browser_dir / original.name
        helper = folder / "check-browser.py"
        helper.write_text("""import sys
sys.path.insert(0, %r)
from claude_china.desktop.platforms.windows_wfp import Engine
from claude_china.desktop.playwright_guard import check_browser
class Store:
    def read(self):
        with Engine(scope=sys.argv[1]) as engine: return engine.read()
    def verify(self, policies):
        with Engine(scope=sys.argv[1]) as engine: return engine.verify(policies)
import json
policy=check_browser(sys.argv[2], Store())
print(json.dumps({'mode':policy.get('mode','proxy') if policy else None}))
""" % str(Path(__file__).resolve().parents[1] / "src"), encoding="utf-8")
        policy = {"playwright": {"mode": "tun", "executables": [str(executable.resolve()), str(browser_exe.resolve())], "tunnel": first.record}}
        with Engine(scope=scope) as engine:
            owner = engine.owner
            engine.replace(policy, {})
            assert engine.verify(policy)
        probe("allowed-selected-tunnel-v4", first.peers[0], True)
        probe("allowed-selected-tunnel-v6", first.peers[1], True)
        probe("allowed-tcp-selected-tunnel-v4", first.peers[0], True, "tcp")
        probe("allowed-tcp-selected-tunnel-v6", first.peers[1], True, "tcp")
        hook = Path(__file__).resolve().parents[1] / "src/claude_china/desktop/ui/playwright-guard.cjs"
        old_options = os.environ.get("NODE_OPTIONS")
        old_helper = os.environ.get("CLAUDEC_BROWSER_GUARD_HELPER")
        os.environ["NODE_OPTIONS"] = "--require=" + json.dumps(hook.as_posix())
        os.environ["CLAUDEC_BROWSER_GUARD_HELPER"] = json.dumps([sys.executable, str(helper), scope])
        try:
            with sync_playwright() as runtime:
                browser = runtime.chromium.launch(executable_path=str(browser_exe), headless=True)
                page = browser.new_page()
                page.goto("http://" + first.peers[0] + ":8080/", timeout=10000)
                assert page.locator("body").inner_text() == "tun-ok"
                cases.append({"case": "playwright-http-through-selected-tun", "result": "tun-ok"})
                candidates = page.evaluate(RTC, "stun:" + first.peers[0] + ":3478")
                assert first.mapped in candidates, ("WebRTC did not use selected TUN", candidates)
                cases.append({"case": "playwright-webrtc-udp-through-selected-tun", "result": first.mapped})
                browser.close()
                unknown = browser_dir / "unregistered.exe"
                shutil.copy2(browser_exe, unknown)
                try:
                    runtime.chromium.launch(executable_path=str(unknown), headless=True)
                    raise AssertionError("Unregistered browser should not start")
                except Exception as error:
                    assert "尚未登记" in str(error), str(error)
                cases.append({"case": "playwright-new-browser-gated-before-spawn", "result": "blocked"})
        finally:
            for key, value in [("NODE_OPTIONS", old_options), ("CLAUDEC_BROWSER_GUARD_HELPER", old_helper)]:
                if value is None: os.environ.pop(key, None)
                else: os.environ[key] = value
        before = second.received
        probe("blocked-other-tunnel-v4", second.peers[0], False)
        probe("blocked-other-tunnel-v6", second.peers[1], False)
        assert second.received == before
        ps("New-NetRoute -DestinationPrefix '%s/32' -InterfaceIndex %d -NextHop 0.0.0.0 -PolicyStore ActiveStore | Out-Null; " % (first.peers[0], second.record["index"]) +
           "New-NetRoute -DestinationPrefix '%s/128' -InterfaceIndex %d -NextHop '::' -PolicyStore ActiveStore | Out-Null" % (first.peers[1], second.record["index"]))
        probe("blocked-route-fallback-v4", first.peers[0], False)
        probe("blocked-route-fallback-v6", first.peers[1], False)
        for process in held:
            output, errors = process.communicate("continue\n", timeout=5)
            assert output.startswith("socket:"), ("Existing UDP flow leaked after route change", output, errors)
            cases.append({"case": "established-udp-flow-cannot-fallback", "result": output})
        assert second.received == before
        ps("$target=@(Get-NetAdapter -IncludeHidden | Where-Object { [guid]$_.InterfaceGuid -eq [guid]'%s' -and $_.Name -eq '%s' }); if($target.Count -ne 1){throw 'Test adapter identity not found'}; $target | Disable-NetAdapter -Confirm:$false" % (first.record["guid"], first.name))
        from claude_china.desktop.platforms.windows_tun import live
        assert not live(first.record), "Disconnected adapter still reported live"
        denied = subprocess.run([sys.executable, str(helper), scope, str(browser_exe)], capture_output=True,
                                env={**os.environ, "PYTHONIOENCODING": "utf-8"}, text=True, encoding="utf-8", timeout=10,
                                creationflags=subprocess.CREATE_NO_WINDOW)
        assert denied.returncode != 0 and "隧道已断开" in denied.stderr, denied.stderr
        cases.append({"case": "browser-gate-rejects-disconnected-tunnel", "result": "blocked"})
        probe("blocked-disconnected-v4", first.peers[0], False)
        probe("blocked-disconnected-v6", first.peers[1], False)
        assert second.received == before
        with Engine(scope=scope) as engine:
            engine.replace({})
            assert engine.verify({})
        probe("restored-fallback-v4", first.peers[0], True)
        probe("restored-fallback-v6", first.peers[1], True)
        assert second.received > before
        result = {"ok": True, "cases": cases}
    except BaseException as error:
        result = {"ok": False, "error": repr(error), "traceback": traceback.format_exc(), "cases": cases,
                  "tunnels": [{"record": tunnel.record, "received": tunnel.received, "debug": tunnel.debug} for tunnel in tunnels]}
    finally:
        for process in held:
            if process.poll() is None:
                process.kill()
                process.wait(5)
        if owner:
            with Engine(owner, scope=scope) as engine:
                engine.replace({})
        for tunnel in reversed(tunnels):
            tunnel.close()
        workspace.cleanup()
    report.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wintun", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    raise SystemExit(run(args.wintun.resolve(), args.report.resolve()))
