import threading
from unittest.mock import Mock

import pytest

from src.code_ai.desktop import animation as animation_mod


def make_animation(monkeypatch, update, interval=0.001):
    frames = [Mock(name="frame-1"), Mock(name="frame-2")]
    rest = Mock(name="rest")
    monkeypatch.setattr(animation_mod, "build_activity_frames", lambda image: frames)
    animation = animation_mod.IconAnimation(rest, update, interval=interval)
    return animation, rest, frames


def test_animation_is_finite_returns_to_rest_and_can_play_again(monkeypatch):
    updates = []
    animation, rest, frames = make_animation(monkeypatch, updates.append)
    try:
        assert updates == []
        animation.play()
        animation._thread.join(timeout=2)
        assert not animation._thread.is_alive()
        assert updates == frames + [rest]

        animation.play()
        animation._thread.join(timeout=2)
        assert updates == (frames + [rest]) * 2
    finally:
        animation.close()


def test_repeated_actions_coalesce_and_stop_interrupts_animation(monkeypatch):
    entered, release = threading.Event(), threading.Event()
    updates = []

    def update(frame):
        updates.append(frame)
        entered.set()
        assert release.wait(timeout=2)

    animation, rest, frames = make_animation(monkeypatch, update, interval=1)
    try:
        animation.play()
        assert entered.wait(timeout=2)
        worker = animation._thread
        for _ in range(10):
            animation.play()
        assert animation._thread is worker
        release.set()
        animation.close()
        assert not worker.is_alive()
        assert updates == frames[:1]
        animation.play()
        assert animation._thread is worker
        animation.close()
        for frame in frames:
            frame.close.assert_called_once_with()
        rest.close.assert_not_called()
    finally:
        release.set()
        animation.close()


def test_failed_frame_does_not_leave_the_icon_in_a_busy_pose(monkeypatch):
    update = Mock(side_effect=[OSError("native update failed"), None])
    animation, rest, _ = make_animation(monkeypatch, update)
    try:
        animation.play()
        animation._thread.join(timeout=2)
        assert not animation._thread.is_alive()
        assert update.call_args.args == (rest,)
    finally:
        animation.close()


def test_unavailable_worker_does_not_break_shutdown(monkeypatch):
    animation, _, frames = make_animation(monkeypatch, Mock())
    worker = Mock()
    worker.start.side_effect = RuntimeError("cannot start new thread")
    worker.join.side_effect = RuntimeError("cannot join thread before it is started")
    monkeypatch.setattr(animation_mod.threading, "Thread", Mock(return_value=worker))

    with pytest.raises(RuntimeError, match="cannot start new thread"):
        animation.play()
    animation.close()
    for frame in frames:
        frame.close.assert_called_once_with()
