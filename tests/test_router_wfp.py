from pathlib import Path
from unittest.mock import Mock
import os
import sys

import pytest

from claude_china.desktop.platforms import windows_wfp as wfp


def test_router_policy_is_narrowly_scoped_to_executables(tmp_path):
    exe = str((tmp_path / 'Claude.exe').resolve())
    wfp.validate({'claude': {'mode': 'router', 'executables': [exe]}})
    with pytest.raises(ValueError):
        wfp.validate({'claude': {'mode': 'router', 'executables': []}})
    with pytest.raises(ValueError):
        wfp.validate({'claude': {'mode': 'router', 'executables': [str(tmp_path / 'not-an-exe')]}})
    with pytest.raises(ValueError):
        wfp.validate({'claude': {'mode': 'router', 'executables': [exe], 'unexpected': True}})


def test_router_network_rules_deny_both_directions_but_allow_loopback_control(monkeypatch):
    monkeypatch.setattr(wfp, '_api', lambda: Mock())
    engine = wfp.Engine(owner='S-1-5-21-123', scope='router:claude')
    captured = []
    monkeypatch.setattr(engine, '_emit', lambda *args, **kwargs: captured.append((args, kwargs)))
    engine._router_filters('claude', 'C:/fixture/Claude.exe', 4, wfp.C.pointer(wfp.Blob()), wfp.Blob(), Mock())
    assert sum(args[4] == wfp.BLOCK for args, _ in captured) == 2
    assert sum(args[4] == wfp.PERMIT for args, _ in captured) == 2
    assert {args[1] for args, _ in captured} == {'claude'}


def test_router_permits_are_dynamic_and_do_not_survive_guardian(monkeypatch):
    monkeypatch.setattr(wfp, '_api', lambda: Mock())
    engine = wfp.Engine(owner='S-1-5-21-123', scope='router:claude', dynamic=True)
    captured = []
    monkeypatch.setattr(engine, '_emit', lambda *args, **kwargs: captured.append((args, kwargs)))
    engine._router_permits('claude', 'C:/fixture/Claude.exe', 4, wfp.C.pointer(wfp.Blob()), wfp.Blob(), Mock())
    assert len(captured) == 2
    assert all(args[4] == wfp.PERMIT for args, _ in captured)
    assert all(kwargs.get('persistent') is False for _, kwargs in captured)


@pytest.mark.skipif(sys.platform != 'win32', reason='Windows token identity')
def test_process_owner_matches_current_user_without_elevation():
    assert wfp.process_sid(os.getpid()) == wfp.current_sid()
