from src.claude_china.desktop.platforms import base


class FakeProc:
    def __init__(self, exe, children=None):
        self.info = {"exe": exe}
        self._children = children or []
        self.terminated = False
        self.killed = False

    def children(self, recursive=False):
        return list(self._children)

    def terminate(self):
        self.terminated = True

    def kill(self):
        self.killed = True


class FakePsutil:
    """Minimal psutil stand-in. `dead_on_wait` controls wait_procs result."""
    def __init__(self, procs, dead_on_wait=True):
        self._procs = procs
        self._dead_on_wait = dead_on_wait

    def process_iter(self, attrs=None):
        return list(self._procs)

    def wait_procs(self, procs, timeout=None):
        if self._dead_on_wait:
            return (list(procs), [])
        return ([], list(procs))


def test_appstatus_display_state():
    assert base.AppStatus("x", found=False).display_state == "not_found"
    assert base.AppStatus("x", found=True, direct=False).display_state == "brokered"
    assert base.AppStatus("x", found=True, direct=True).display_state == "direct"


def test_any_process_under_matches_directory_prefix(monkeypatch):
    procs = [FakeProc(r"C:\Apps\Claude\app\Claude.exe"), FakeProc(r"C:\Other\thing.exe")]
    monkeypatch.setattr(base, "psutil", FakePsutil(procs))
    assert base.any_process_under([r"C:\Apps\Claude"]) is True
    assert base.any_process_under([r"C:\Nope"]) is False
    assert base.any_process_under([""]) is False


def test_matches_windows_style_paths_under_posix_abspath(monkeypatch):
    # GitHub Actions runs these Windows backend tests on Linux. os.path.abspath
    # there prefixes the repo cwd but leaves backslashes intact.
    monkeypatch.setattr(base.os.path, "abspath", lambda p: "/repo/" + p)
    monkeypatch.setattr(base.os.path, "normcase", lambda p: p)
    monkeypatch.setattr(base.os, "sep", "/")

    assert base._matches(
        r"C:\Apps\Claude\app\Claude.exe",
        r"C:\Apps\Claude",
    ) is True


def test_ignored_exe_matches_windows_style_path_under_posix_basename(monkeypatch):
    # POSIX basename treats backslashes as ordinary characters.
    monkeypatch.setattr(base.os.path, "basename", lambda p: p.rsplit("/", 1)[-1])

    assert base._ignored_exe(
        r"C:\Apps\Claude\app\resources\cowork-svc.exe",
        {"cowork-svc.exe"},
    ) is True


def test_stop_terminates_matches_and_children_not_others(monkeypatch):
    child = FakeProc(r"C:\Apps\Claude\helper.exe")
    match = FakeProc(r"C:\Apps\Claude\app\Claude.exe", children=[child])
    other = FakeProc(r"C:\Other\thing.exe")
    monkeypatch.setattr(base, "psutil", FakePsutil([match, other], dead_on_wait=True))

    base.stop_processes_under([r"C:\Apps\Claude"])

    assert match.terminated is True
    assert child.terminated is True
    assert other.terminated is False
    assert match.killed is False  # died on terminate, no kill needed


def test_stop_kills_stragglers(monkeypatch):
    match = FakeProc(r"C:\Apps\Claude\app\Claude.exe")
    monkeypatch.setattr(base, "psutil", FakePsutil([match], dead_on_wait=False))

    base.stop_processes_under([r"C:\Apps\Claude"])

    assert match.terminated is True
    assert match.killed is True


def test_stop_continues_when_terminate_raises(monkeypatch):
    # A proc dying mid-sweep must not abort termination of the rest.
    class TerminateRaisingProc(FakeProc):
        def terminate(self):
            raise RuntimeError("already gone")

    raising = TerminateRaisingProc(r"C:\Apps\Claude\app\Claude.exe")
    normal = FakeProc(r"C:\Apps\Claude\app\helper.exe")
    monkeypatch.setattr(base, "psutil", FakePsutil([raising, normal], dead_on_wait=True))

    count = base.stop_processes_under([r"C:\Apps\Claude"])

    assert normal.terminated is True   # sweep continued past the raising proc
    assert count == 2


def test_stop_continues_when_children_raises(monkeypatch):
    # If enumerating a proc's children fails, the proc itself is still stopped.
    class ChildrenRaisingProc(FakeProc):
        def children(self, recursive=False):
            raise RuntimeError("access denied")

    match = ChildrenRaisingProc(r"C:\Apps\Claude\app\Claude.exe")
    monkeypatch.setattr(base, "psutil", FakePsutil([match], dead_on_wait=True))

    count = base.stop_processes_under([r"C:\Apps\Claude"])

    assert match.terminated is True
    assert count == 1


def test_stop_kills_targets_when_wait_procs_raises(monkeypatch):
    # A service-managed process can refuse wait access after terminate() was
    # attempted. That must not surface as a failed stop action.
    class WaitRaisingPsutil(FakePsutil):
        def wait_procs(self, procs, timeout=None):
            raise RuntimeError("access denied")

    match = FakeProc(r"C:\Apps\Claude\app\resources\cowork-svc.exe")
    monkeypatch.setattr(base, "psutil", WaitRaisingPsutil([match]))

    count = base.stop_processes_under([r"C:\Apps\Claude"])

    assert match.terminated is True
    assert match.killed is True
    assert count == 1


def test_psutil_lazy_import_caches(monkeypatch):
    # _psutil() must import psutil on first use and cache it in the module global.
    import builtins

    sentinel = object()
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "psutil":
            return sentinel
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(base, "psutil", None)
    monkeypatch.setattr(builtins, "__import__", fake_import)

    assert base._psutil() is sentinel   # triggers the lazy import branch
    assert base.psutil is sentinel      # and caches into the global
