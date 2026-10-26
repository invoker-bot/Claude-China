import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


@pytest.mark.parametrize("method", ["spawn", "spawnSync", "execFile", "execFileSync"])
@pytest.mark.parametrize("browser, flag", [("chrome.exe", "--remote-debugging-pipe"),
                                         ("custom-firefox.exe", "-juggler-pipe"),
                                         ("custom-webkit.exe", "--inspector-pipe")])
def test_browser_is_denied_before_process_creation(method, browser, flag):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is not installed")
    hook = Path(__file__).parents[1] / "src/claude_china/desktop/ui/playwright-guard.cjs"
    env = dict(os.environ)
    env["NODE_OPTIONS"] = "--require=" + json.dumps(hook.as_posix())
    env["CLAUDEC_BROWSER_GUARD_HELPER"] = json.dumps([sys.executable, "-c", "import sys;sys.stderr.write('guard denied');sys.exit(1)"])
    script = "try { require('child_process')[process.argv[1]](process.argv[2], [process.argv[3]]); process.exit(2); } catch(error) { if (!error.message.includes('guard denied')) throw error; }"
    result = subprocess.run([node, "-e", script, method, browser, flag], env=env, capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr


def test_non_browser_tools_are_not_blocked_by_the_preload():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is not installed")
    hook = Path(__file__).parents[1] / "src/claude_china/desktop/ui/playwright-guard.cjs"
    env = dict(os.environ, NODE_OPTIONS="--require=" + json.dumps(hook.as_posix()),
               CLAUDEC_BROWSER_GUARD_HELPER=json.dumps(["missing-guard-helper"]))
    result = subprocess.run([node, "-e", "const r=require('child_process').spawnSync(process.execPath,['-e','process.stdout.write(\"ok\")'],{encoding:'utf8'}); if(r.stdout!=='ok')process.exit(1);"],
                            env=env, capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr


def test_tun_browser_uses_tunnel_routing_without_changing_cli_proxy_environment():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is not installed")
    hook = Path(__file__).parents[1] / "src/claude_china/desktop/ui/playwright-guard.cjs"
    env = dict(os.environ)
    env.pop("NODE_OPTIONS", None)
    env["HTTP_PROXY"] = "http://local-proxy:9999"
    env["CLAUDEC_BROWSER_GUARD_HELPER"] = json.dumps([sys.executable, "-c", "print('{\"mode\":\"tun\"}')"])
    script = """const cp=require('child_process'), original=cp.spawnSync;
cp.spawnSync=function(file,args,options){
 if(file==='chrome.exe') {console.log(JSON.stringify({args,env:options.env}));return {status:0};}
 return original(file,args,options);
};
require(process.argv[1]);
cp.spawnSync('chrome.exe',['--remote-debugging-pipe'],{});
if(process.env.HTTP_PROXY!=='http://local-proxy:9999')process.exit(3);
"""
    result = subprocess.run([node, "-e", script, str(hook)], env=env, capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    call = json.loads(result.stdout)
    assert "--no-proxy-server" in call["args"]
    assert not any(key.lower() in ("http_proxy", "https_proxy", "all_proxy", "no_proxy") for key in call["env"])
