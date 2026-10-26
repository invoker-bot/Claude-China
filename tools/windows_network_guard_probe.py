"""Isolated native WFP acceptance test. Run elevated; never protects real apps.

Only a temporary test EXE and a unique WFP provider are used. The provider is
removed in finally, including after a failed assertion. No Internet required.
"""

import argparse
import ctypes
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import traceback
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from claude_china.desktop.platforms.windows_wfp import Engine

SOURCE = r'''
using System;
using System.Net;
using System.Net.Sockets;
class Probe {
    static void Hold(string mode, string address, int port) {
        var ip = IPAddress.Parse(address);
        using (var socket = new Socket(ip.AddressFamily,
                mode == "udp" ? SocketType.Dgram : SocketType.Stream,
                mode == "udp" ? ProtocolType.Udp : ProtocolType.Tcp)) {
            socket.SendTimeout = 800; socket.ReceiveTimeout = 800;
            socket.Connect(new IPEndPoint(ip, port));
            socket.Send(new byte[20]); socket.Receive(new byte[64]);
            Console.WriteLine("ready");
            Console.ReadLine();
            socket.Send(new byte[20]); socket.Receive(new byte[64]);
        }
    }
    static void Connect(string mode, string address, int port) {
        var ip = IPAddress.Parse(address);
        using (var socket = new Socket(ip.AddressFamily,
                mode == "udp" ? SocketType.Dgram : SocketType.Stream,
                mode == "udp" ? ProtocolType.Udp : ProtocolType.Tcp)) {
            socket.SendTimeout = 800; socket.ReceiveTimeout = 800;
            socket.Connect(new IPEndPoint(ip, port));
            if (mode == "udp") {
                byte[] request = new byte[20];
                request[1] = 1; request[4] = 0x21; request[5] = 0x12;
                request[6] = 0xa4; request[7] = 0x42;
                socket.Send(request); socket.Receive(new byte[64]);
            }
        }
    }
    static int Main(string[] args) {
        try {
            if (args[0].StartsWith("hold-")) {
                Hold(args[0].Substring(5), args[1], Int32.Parse(args[2]));
            } else if (args[0] == "fallback") {
                try { Connect("tcp", args[1], Int32.Parse(args[2])); }
                catch (SocketException) { Connect("tcp", args[1], Int32.Parse(args[3])); }
            } else { Connect(args[0], args[1], Int32.Parse(args[2])); }
            Console.Write("ok"); return 0;
        } catch (SocketException error) {
            Console.Write("socket:" + error.ErrorCode); return 1;
        }
    }
}
'''


class Server:
    def __init__(self, family, udp=False):
        self.udp = udp
        self.received = 0
        self.closed = threading.Event()
        self.socket = socket.socket(family, socket.SOCK_DGRAM if udp else socket.SOCK_STREAM)
        self.socket.bind(("::1" if family == socket.AF_INET6 else "127.0.0.1", 0))
        self.address, self.port = self.socket.getsockname()[:2]
        if not udp:
            self.socket.listen(8)
        self.socket.settimeout(.1)
        self.thread = threading.Thread(target=self.serve, daemon=True)
        self.thread.start()

    def serve(self):
        while not self.closed.is_set():
            try:
                if self.udp:
                    data, peer = self.socket.recvfrom(64)
                    self.received += 1
                    self.socket.sendto(data, peer)
                else:
                    client, _ = self.socket.accept()
                    threading.Thread(target=self.echo_tcp, args=(client,), daemon=True).start()
            except socket.timeout:
                pass
            except OSError:
                break

    def echo_tcp(self, client):
        client.settimeout(.1)
        try:
            while not self.closed.is_set():
                try:
                    data = client.recv(64)
                    if not data:
                        break
                    self.received += 1
                    client.sendall(data)
                except socket.timeout:
                    pass
        except OSError:
            pass
        finally:
            client.close()

    def close(self):
        self.closed.set()
        self.socket.close()
        self.thread.join(1)


def run(report):
    results = []
    scope = "probe-" + uuid.uuid4().hex
    servers = []
    held = []
    engine_owner = None
    try:
        assert sys.platform == "win32" and ctypes.windll.shell32.IsUserAnAdmin(), "Run this isolated probe elevated"
        with tempfile.TemporaryDirectory(prefix="claudec-wfp-probe-") as directory:
            directory = Path(directory)
            source = directory / "Probe.cs"
            source.write_text(SOURCE, encoding="utf-8")
            executable, control = directory / "GuardProbe.exe", directory / "Control.exe"
            compiler = Path(os.environ["WINDIR"]) / "Microsoft.NET/Framework64/v4.0.30319/csc.exe"
            subprocess.run([str(compiler), "/nologo", "/out:" + str(executable), str(source)],
                           check=True, capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
            shutil.copy2(executable, control)

            def check(label, exe, mode, server, denied=False, fallback=None):
                received = server.received
                command = [str(exe), mode, server.address, str(server.port)]
                if fallback is not None:
                    command.append(str(fallback.port))
                result = subprocess.run(command, capture_output=True, text=True, timeout=5,
                                        creationflags=subprocess.CREATE_NO_WINDOW)
                expected = ["socket:10013", "socket:10060"] if denied and mode == "udp" else ["socket:10013"] if denied else ["ok"]
                assert result.stdout in expected, (label, result.returncode, result.stdout, result.stderr)
                if denied and mode == "udp":
                    assert server.received == received, "Blocked UDP request reached its destination"
                results.append({"case": label, "result": result.stdout})

            tcp4, udp4 = Server(socket.AF_INET), Server(socket.AF_INET, True)
            tcp6, udp6 = Server(socket.AF_INET6), Server(socket.AF_INET6, True)
            proxy4, proxy6 = Server(socket.AF_INET), Server(socket.AF_INET6)
            servers.extend([tcp4, udp4, tcp6, udp6, proxy4, proxy6])
            for server, mode in [(tcp4, "tcp"), (udp4, "udp"), (tcp6, "tcp"), (udp6, "udp")]:
                check("before-" + mode + "-" + server.address, executable, mode, server)

            for mode, server in [("tcp", tcp4), ("udp", udp4), ("tcp", tcp6), ("udp", udp6)]:
                process = subprocess.Popen([str(executable), "hold-" + mode, server.address, str(server.port)],
                                           stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                           text=True, creationflags=subprocess.CREATE_NO_WINDOW)
                held.append((mode, server, process))
                assert process.stdout.readline().strip() == "ready", "Could not establish pre-existing flow"

            policy = {"claude": {"executables": [str(executable)],
                                  "proxy": {"addresses": [proxy4.address], "port": proxy4.port}}}
            with Engine(scope=scope) as engine:
                engine_owner = engine.owner
                engine.replace(policy, {})
                if not engine.verify(policy):
                    expected, actual = {}, {}
                    engine._build(policy, lambda item: expected.update({str(item.key): engine._signature(item)}))
                    engine._filters(lambda item: actual.update({str(item.key): engine._signature(item)}))
                    raise AssertionError({"expected": expected, "actual": actual})
            # The engine has closed: enforcement must remain active.
            check("proxy-v4-allowed-after-engine-exit", executable, "tcp", proxy4)
            for mode, server, process in held:
                received = server.received
                output, errors = process.communicate("continue\n", timeout=5)
                assert output.startswith("socket:"), ("Pre-existing direct flow survived", mode, output, errors)
                assert received == server.received, "Pre-existing direct flow leaked a packet"
                results.append({"case": "existing-" + mode + "-" + server.address + "-blocked", "result": output})
            for server, mode in [(tcp4, "tcp"), (udp4, "udp"), (tcp6, "tcp"), (udp6, "udp")]:
                check("blocked-" + mode + "-" + server.address, executable, mode, server, True)
                check("other-application-unaffected-" + mode + "-" + server.address, control, mode, server)

            with Engine(scope=scope) as engine:
                original_build = engine._build
                engine._build = lambda *_: (_ for _ in ()).throw(RuntimeError("Injected mid-transaction failure"))
                try:
                    engine.replace(policy, policy)
                    raise AssertionError("Expected transaction failure")
                except RuntimeError:
                    pass
                engine._build = original_build
                assert engine.verify(policy), "Failed transaction damaged previous filters"
            check("rollback-still-blocks", executable, "tcp", tcp4, True)
            with Engine(scope=scope) as engine:
                try:
                    engine.replace({}, expected={})
                    raise AssertionError("Stale policy update should be rejected")
                except ValueError:
                    pass
                assert engine.verify(policy)
            check("stale-update-still-blocks", executable, "tcp", tcp4, True)
            proxy4.close()
            check("proxy-offline-cannot-fallback", executable, "fallback", proxy4, True, tcp4)

            policy["claude"]["proxy"] = {"addresses": [proxy6.address], "port": proxy6.port}
            with Engine(scope=scope) as engine:
                engine.replace(policy)
                assert engine.verify(policy)
            check("proxy-v6-allowed", executable, "tcp", proxy6)
            check("v4-direct-still-blocked-with-v6-proxy", executable, "tcp", tcp4, True)
            with Engine(scope=scope) as engine:
                engine.replace({})
                assert engine.read() == {} and engine.verify({})
            for server, mode in [(tcp4, "tcp"), (udp4, "udp"), (tcp6, "tcp"), (udp6, "udp")]:
                check("restored-" + mode + "-" + server.address, executable, mode, server)
        report.write_text(json.dumps({"ok": True, "cases": results}, indent=2), encoding="utf-8")
        return 0
    except BaseException as error:
        report.write_text(json.dumps({"ok": False, "error": repr(error), "traceback": traceback.format_exc(), "cases": results}, indent=2), encoding="utf-8")
        return 1
    finally:
        for _, _, process in held:
            if process.poll() is None:
                process.kill()
                process.wait(5)
        for server in servers:
            server.close()
        if engine_owner:
            with Engine(engine_owner, scope=scope) as engine:
                engine.replace({})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    raise SystemExit(run(parser.parse_args().report.resolve()))
