"""Test router watchdog filters with disposable EXEs and loopback servers only.

Run elevated. A unique WFP provider is always removed in finally; no installed
application, proxy, tunnel, or existing network guard is modified.
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

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from claude_china.desktop.platforms.windows_wfp import Engine
from claude_china.desktop.router_guardian import guard_session
from windows_network_guard_probe import SOURCE

SESSION_SOURCE = r'''
using System;
using System.Net;
using System.Net.Sockets;
class SessionProbe {
    static void Main(string[] args) {
        Console.WriteLine("ready");
        string line;
        while ((line = Console.ReadLine()) != null && line != "quit") {
            try {
                using (var s = new Socket(AddressFamily.InterNetwork, SocketType.Stream, ProtocolType.Tcp)) {
                    s.SendTimeout = 800; s.ReceiveTimeout = 800;
                    s.Connect(new IPEndPoint(IPAddress.Parse(args[0]), Int32.Parse(args[1])));
                    Console.WriteLine("connected");
                }
            } catch (SocketException) { Console.WriteLine("blocked"); }
        }
    }
}
'''


class Server:
    def __init__(self, address, udp=False):
        self.udp = udp
        self.received = 0
        self.closed = threading.Event()
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM if udp else socket.SOCK_STREAM)
        self.socket.bind((address, 0))
        self.address, self.port = self.socket.getsockname()
        if not udp:
            self.socket.listen(8)
        self.socket.settimeout(.1)
        threading.Thread(target=self.serve, daemon=True).start()

    def serve(self):
        while not self.closed.is_set():
            try:
                if self.udp:
                    data, peer = self.socket.recvfrom(64)
                    self.received += 1
                    self.socket.sendto(data, peer)
                else:
                    client, _ = self.socket.accept()
                    threading.Thread(target=self.echo, args=(client,), daemon=True).start()
            except socket.timeout:
                continue
            except OSError:
                break

    def echo(self, client):
        client.settimeout(.1)
        try:
            while not self.closed.is_set():
                try:
                    data = client.recv(64)
                    if not data:
                        return
                    self.received += 1
                    client.sendall(data)
                except socket.timeout:
                    continue
        except OSError:
            pass
        finally:
            client.close()

    def close(self):
        self.closed.set()
        self.socket.close()


def hold_permit(owner, scope, executable):
    policy = {'claude': {'mode': 'router', 'executables': [executable]}}
    with Engine(owner, scope=scope, dynamic=True) as dynamic:
        dynamic.add_router_permits(policy)
        if not dynamic.verify_router_permits(policy):
            return 1
        print('ready', flush=True)
        sys.stdin.readline()
    return 0


def read_ready(child):
    result = []
    done = threading.Event()
    def read():
        try:
            result.append(child.stdout.readline().strip())
        finally:
            done.set()
    threading.Thread(target=read, daemon=True).start()
    if not done.wait(15) or not result or result[0] != 'ready':
        raise RuntimeError('Probe did not become ready')


def run(report):
    scope = 'router-test-' + uuid.uuid4().hex
    results, servers, held = [], [], []
    owner = None
    helper = None
    session = None
    directory = None
    try:
        assert sys.platform == 'win32' and ctypes.windll.shell32.IsUserAnAdmin(), 'Run elevated'
        directory = tempfile.TemporaryDirectory(prefix='claudec-router-native-')
        root = Path(directory.name)
        source, target, control = root / 'Probe.cs', root / 'GuardProbe.exe', root / 'Control.exe'
        source.write_text(SOURCE, encoding='utf-8')
        compiler = Path(os.environ['WINDIR']) / 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
        subprocess.run([str(compiler), '/nologo', '/out:' + str(target), str(source)],
                       check=True, capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
        shutil.copy2(target, control)
        tcp, udp, local = Server('127.0.0.2'), Server('127.0.0.2', True), Server('127.0.0.1')
        servers.extend((tcp, udp, local))

        def check(name, exe, mode, server, blocked=False):
            received = server.received
            result = subprocess.run([str(exe), mode, server.address, str(server.port)],
                                    capture_output=True, text=True, timeout=5,
                                    creationflags=subprocess.CREATE_NO_WINDOW)
            assert (result.returncode != 0) if blocked else (result.returncode == 0), (name, result.stdout, result.stderr)
            if blocked and mode == 'udp':
                assert server.received == received, 'Blocked UDP packet reached the server'
            results.append(name)

        check('baseline-tcp', target, 'tcp', tcp)
        check('baseline-udp', target, 'udp', udp)
        policy = {'claude': {'mode': 'router', 'executables': [str(target)]}}
        with Engine(scope=scope) as static:
            owner = static.owner
            static.replace(policy, expected={})
            assert static.verify(policy)
        check('persistent-deny', target, 'tcp', tcp, blocked=True)

        helper = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), '--hold', owner, scope, str(target)],
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                  text=True, creationflags=subprocess.CREATE_NO_WINDOW)
        read_ready(helper)
        with Engine(owner, scope=scope) as static:
            assert static.router_permits_present(policy)
        check('healthy-tcp', target, 'tcp', tcp)
        check('healthy-udp', target, 'udp', udp)
        for mode, server in [('tcp', tcp), ('udp', udp)]:
            child = subprocess.Popen([str(target), 'hold-' + mode, server.address, str(server.port)],
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                     text=True, creationflags=subprocess.CREATE_NO_WINDOW)
            held.append((mode, server, child))
            read_ready(child)

        # Simulate a watchdog crash. BFE removes only this session's permits.
        helper.kill()
        helper.wait(timeout=5)
        helper = None
        with Engine(owner, scope=scope) as static:
            assert not static.router_permits_present(policy)
        for mode, server, child in held:
            received = server.received
            out, err = child.communicate('continue\n', timeout=5)
            assert child.returncode != 0, (mode, out, err)
            assert server.received == received, 'Existing flow leaked after permit removal'
            results.append('existing-' + mode + '-blocked')
        check('new-tcp-blocked', target, 'tcp', tcp, blocked=True)
        check('new-udp-blocked', target, 'udp', udp, blocked=True)
        check('loopback-control-kept', target, 'tcp', local)
        check('unrelated-exe-unaffected', control, 'tcp', tcp)
        with Engine(owner, scope=scope) as static:
            assert static.verify(policy)
            static.replace({}, expected=policy)
        check('restored-tcp', target, 'tcp', tcp)
        check('restored-udp', target, 'udp', udp)

        session_source, session_exe = root / 'Session.cs', root / 'SessionProbe.exe'
        session_source.write_text(SESSION_SOURCE, encoding='utf-8')
        subprocess.run([str(compiler), '/nologo', '/out:' + str(session_exe), str(session_source)],
                       check=True, capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
        session_policy = {'claude': {'mode': 'router', 'executables': [str(session_exe)]}}
        ready, fail, complete = threading.Event(), threading.Event(), threading.Event()
        outcomes = []
        def run_guard():
            try:
                outcomes.append(guard_session(session_policy,
                    lambda active=False: Engine(owner, scope=scope, dynamic=active),
                    lambda *_: (fail.wait(15) and 'simulated-network-failure') or None,
                    ready.set, lambda reason: None))
            finally:
                complete.set()
        threading.Thread(target=run_guard, daemon=True).start()
        assert ready.wait(10), 'Guardian did not become ready'
        session = subprocess.Popen([str(session_exe), tcp.address, str(tcp.port)],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   text=True, creationflags=subprocess.CREATE_NO_WINDOW)
        read_ready(session)
        session.stdin.write('probe\n'); session.stdin.flush()
        assert session.stdout.readline().strip() == 'connected'
        fail.set()
        assert complete.wait(10) and outcomes == ['blocked']
        session.stdin.write('probe\n'); session.stdin.flush()
        assert session.stdout.readline().strip() == 'blocked' and session.poll() is None
        results.append('session-preserved-after-network-failure')
        session.stdin.write('quit\n'); session.stdin.flush()
        session.wait(timeout=5)
        session = None
        session_exe.unlink()
        with Engine(owner, scope=scope) as static:
            assert not static.router_permits_present(session_policy)
            static.replace({}, expected=session_policy)
        results.append('restore-after-executable-removed')
        report.write_text(json.dumps({'ok': True, 'cases': results}, indent=2), encoding='utf-8')
        return 0
    except BaseException as error:
        report.write_text(json.dumps({'ok': False, 'error': repr(error), 'traceback': traceback.format_exc(),
                                      'cases': results}, indent=2), encoding='utf-8')
        return 1
    finally:
        if helper and helper.poll() is None:
            helper.kill()
            helper.wait(timeout=5)
        if session and session.poll() is None:
            session.kill()
            session.wait(timeout=5)
        for _, _, child in held:
            if child.poll() is None:
                child.kill()
                child.wait(timeout=5)
        for server in servers:
            server.close()
        if owner:
            with Engine(owner, scope=scope) as static:
                if static.read():
                    static.replace({})
        if directory:
            directory.cleanup()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', type=Path)
    parser.add_argument('--hold', nargs=3)
    options = parser.parse_args()
    if options.hold:
        raise SystemExit(hold_permit(*options.hold))
    if not options.report:
        parser.error('--report is required')
    raise SystemExit(run(options.report.resolve()))
