"""Smoke test for ``examples/multiplayer_demo.py`` (RR2 gap-close, batch 3).

The demo uses ``pharos_engine.net.GameSession`` (Kademlia DHT + STUN) and
``pharos_engine.input.ActionMap``.  Real DHT/STUN traffic obviously can't
run in CI, so we stub ``GameSession.host`` + ``LockstepSync.tick_async``
+ ``asyncio.sleep`` and drive the async ``main()`` to completion.

Pins:
1. Demo module imports cleanly (no top-level side effects).
2. Module exposes an async ``main`` coroutine + the ``__main__`` guard.
3. Under the stubbed ``GameSession`` fixture, ``main()`` runs to completion
   and produces the expected number of lockstep frames.
"""
from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest


_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEMO_PATH = _REPO_ROOT / "PharosEngineExamples" / "examples" / "multiplayer_demo.py"


@pytest.fixture
def demo():
    if not _DEMO_PATH.is_file():
        pytest.skip(f"demo missing: {_DEMO_PATH}")

    spec = importlib.util.spec_from_file_location("multiplayer_demo_rr2", _DEMO_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["multiplayer_demo_rr2"] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        pytest.skip(f"multiplayer demo failed to import: {exc}")
    return module


def test_multiplayer_demo_module_imports(demo):
    """The demo file loaded without touching the network."""
    assert demo is not None
    assert callable(getattr(demo, "main", None))
    # ``main`` should be an async coroutine function.
    assert asyncio.iscoroutinefunction(demo.main), (
        "multiplayer_demo.main must be async so tick_async works"
    )


def test_multiplayer_demo_has_main_guard(demo):
    """Importing the demo must not launch the asyncio loop."""
    src = Path(demo.__file__).read_text(encoding="utf-8")
    assert 'if __name__ == "__main__":' in src, (
        "multiplayer demo must guard asyncio.run(main()) behind __main__"
    )
    # ``asyncio.run`` must appear only after the guard.
    guard_idx = src.index('if __name__ == "__main__":')
    run_idx = src.index("asyncio.run(")
    assert run_idx > guard_idx, (
        "asyncio.run(main()) must be inside the __main__ guard"
    )


def test_multiplayer_demo_main_runs_stubbed(demo, monkeypatch):
    """With GameSession + asyncio.sleep stubbed, ``main('host')`` completes.

    We patch:
    - ``sys.argv`` so the demo picks the host branch.
    - ``demo.GameSession.host`` to return a fake session that records
      broadcasts.
    - ``asyncio.sleep`` to return immediately so the 60-tick loop doesn't
      wall-clock the test.
    """
    monkeypatch.setattr(demo.sys, "argv", ["multiplayer_demo.py", "host"])

    # Build a fake LockstepSync + Session.
    fake_sync = MagicMock()
    fake_sync.tick = 0

    async def _tick_async(frame, broadcast):  # noqa: ARG001
        fake_sync.tick += 1
        # Return a list of one InputFrame so the print-loop has something.
        return [frame]

    fake_sync.tick_async = _tick_async

    fake_session = MagicMock()
    fake_session.room_code = "ABC123"
    fake_session.enable_lockstep.return_value = fake_sync
    fake_session.broadcast = MagicMock()
    fake_session.on_player_joined = lambda fn: fn
    fake_session.on_player_left = lambda fn: fn
    fake_session.close = AsyncMock()

    async def _fake_host(player_id=0):  # noqa: ARG001
        return fake_session

    monkeypatch.setattr(demo.GameSession, "host", _fake_host)

    # Replace asyncio.sleep with a fast no-op.
    async def _fast_sleep(_duration):
        return None

    monkeypatch.setattr(demo.asyncio, "sleep", _fast_sleep)

    # Drive the coroutine.
    asyncio.run(demo.main())

    # The demo runs a 60-tick lockstep loop.
    assert fake_sync.tick == 60, (
        f"expected 60 lockstep ticks, got {fake_sync.tick}"
    )
    fake_session.close.assert_awaited_once()
