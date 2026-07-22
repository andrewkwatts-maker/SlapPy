"""SS1 STUB-triage tests — round 20 of feature-map wiring.

Covers the five new action ids added by the SS1 sprint tick (round 20
after RR1's round-19 ``edit.select_similar`` / ``theme.reset_to_default``
/ ``layer.hide_others`` / ``layer.isolate`` /
``snap.toggle_incremental`` batch):

* ``content.reveal_in_explorer`` — reveal the *item itself* selected
  inside the OS file explorer (distinct from
  ``content.reveal_in_folder`` which just opens the parent path).
* ``content.duplicate_folder`` — folder-only variant of
  ``content.duplicate_asset``; rejects file paths with
  ``not_a_folder``.
* ``view.increase_pixel_scale`` — step the integer pixel-scale
  factor up (clamps at ``max_scale`` = 8).
* ``view.decrease_pixel_scale`` — step it down (clamps at
  ``min_scale`` = 1).
* ``spawn.stamp_repeat`` — hold-and-stamp N copies of the most-recent
  spawn along a stride (with optional per-axis jitter). Distinct from
  ``spawn.spawn_batch_row`` (identical stride but no jitter, no
  ``_stamp_history`` slot) and ``spawn.repeat_last`` (single one-shot).

Every test dispatches through :class:`~pharos_editor.tool_router.ToolRouter`
so the wire-up is exercised end-to-end. No DPG context — fixtures use
:class:`SimpleNamespace` stand-ins for shell / browser handles.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from pharos_editor.tool_router import (
    REGISTRY,
    ToolRouter,
    register_default_actions,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def router() -> ToolRouter:
    r = ToolRouter()
    register_default_actions(r)
    return r


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


class TestRegistration:
    def test_content_reveal_in_explorer_registered(
        self, router: ToolRouter,
    ) -> None:
        assert router.has_action("content.reveal_in_explorer")

    def test_content_duplicate_folder_registered(
        self, router: ToolRouter,
    ) -> None:
        assert router.has_action("content.duplicate_folder")

    def test_view_increase_pixel_scale_registered(
        self, router: ToolRouter,
    ) -> None:
        assert router.has_action("view.increase_pixel_scale")

    def test_view_decrease_pixel_scale_registered(
        self, router: ToolRouter,
    ) -> None:
        assert router.has_action("view.decrease_pixel_scale")

    def test_spawn_stamp_repeat_registered(
        self, router: ToolRouter,
    ) -> None:
        assert router.has_action("spawn.stamp_repeat")

    def test_all_ss1_on_module_singleton(self) -> None:
        for aid in (
            "content.reveal_in_explorer",
            "content.duplicate_folder",
            "view.increase_pixel_scale",
            "view.decrease_pixel_scale",
            "spawn.stamp_repeat",
        ):
            assert REGISTRY.has_action(aid), aid

    def test_ss1_categories(self, router: ToolRouter) -> None:
        expected = {
            "content.reveal_in_explorer": "content",
            "content.duplicate_folder": "content",
            "view.increase_pixel_scale": "view",
            "view.decrease_pixel_scale": "view",
            "spawn.stamp_repeat": "spawn",
        }
        for aid, cat in expected.items():
            action = router.get(aid)
            assert action is not None, aid
            assert action.category == cat, aid


# ---------------------------------------------------------------------------
# content.reveal_in_explorer
# ---------------------------------------------------------------------------


class TestContentRevealInExplorer:
    def test_missing_path(self, router: ToolRouter) -> None:
        result = router.dispatch("content.reveal_in_explorer", {})
        assert result == {"status": "missing_path"}

    def test_empty_string_path(self, router: ToolRouter) -> None:
        result = router.dispatch(
            "content.reveal_in_explorer", {"path": ""},
        )
        assert result == {"status": "missing_path"}

    def test_not_found(self, router: ToolRouter, tmp_path: Path) -> None:
        stale = tmp_path / "nope" / "phantom.png"
        result = router.dispatch(
            "content.reveal_in_explorer", {"path": str(stale)},
        )
        assert result["status"] == "not_found"
        assert result["path"] == str(stale)

    def test_reveal_existing_file(
        self,
        router: ToolRouter,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Stub subprocess.Popen so we do not actually launch Explorer.
        launched: list[list[str]] = []

        def fake_popen(argv: list[str]) -> object:
            launched.append(list(argv))
            return object()

        import pharos_editor.actions.content_reveal_explorer_actions as mod
        monkeypatch.setattr(mod.subprocess, "Popen", fake_popen)

        target = tmp_path / "hero.png"
        target.write_bytes(b"\x89PNG\r\n")
        result = router.dispatch(
            "content.reveal_in_explorer", {"path": str(target)},
        )
        assert result["status"] == "revealed"
        assert result["path"] == str(target)
        assert result["platform"] in {"win32", "darwin", "linux"}
        assert result["mode"] in {"select", "open_parent"}
        assert len(launched) == 1


# ---------------------------------------------------------------------------
# content.duplicate_folder
# ---------------------------------------------------------------------------


class TestContentDuplicateFolder:
    def test_missing_path(self, router: ToolRouter) -> None:
        result = router.dispatch("content.duplicate_folder", {})
        assert result == {"status": "missing_path"}

    def test_not_found(self, router: ToolRouter, tmp_path: Path) -> None:
        stale = tmp_path / "does_not_exist"
        result = router.dispatch(
            "content.duplicate_folder", {"path": str(stale)},
        )
        assert result["status"] == "not_found"
        assert result["path"] == str(stale)

    def test_rejects_file(
        self, router: ToolRouter, tmp_path: Path,
    ) -> None:
        f = tmp_path / "actually_a_file.txt"
        f.write_text("hello")
        result = router.dispatch(
            "content.duplicate_folder", {"path": str(f)},
        )
        assert result["status"] == "not_a_folder"
        assert result["path"] == str(f)

    def test_duplicates_folder(
        self, router: ToolRouter, tmp_path: Path,
    ) -> None:
        src = tmp_path / "Sprites"
        src.mkdir()
        (src / "hero.png").write_bytes(b"\x89PNG")
        (src / "villain.png").write_bytes(b"\x89PNG-X")
        result = router.dispatch(
            "content.duplicate_folder", {"path": str(src)},
        )
        assert result["status"] == "duplicated"
        dst = Path(result["copy"])
        assert dst.exists() and dst.is_dir()
        assert (dst / "hero.png").exists()
        assert (dst / "villain.png").exists()
        assert result["name"] == "Sprites_copy"
        assert result["file_count"] == 2

    def test_uniquify_on_collision(
        self, router: ToolRouter, tmp_path: Path,
    ) -> None:
        src = tmp_path / "Sprites"
        src.mkdir()
        (src / "x.txt").write_text("x")
        # First duplicate → Sprites_copy
        r1 = router.dispatch(
            "content.duplicate_folder", {"path": str(src)},
        )
        assert Path(r1["copy"]).name == "Sprites_copy"
        # Second duplicate → Sprites_copy_2 (source is Sprites; base is
        # Sprites_copy which now exists, so uniquify walks to _2)
        r2 = router.dispatch(
            "content.duplicate_folder", {"path": str(src)},
        )
        assert Path(r2["copy"]).name == "Sprites_copy_2"


# ---------------------------------------------------------------------------
# view.increase_pixel_scale / view.decrease_pixel_scale
# ---------------------------------------------------------------------------


class TestViewPixelScale:
    def test_increase_from_default(self, router: ToolRouter) -> None:
        shell = SimpleNamespace(_pixel_scale=1)
        result = router.dispatch(
            "view.increase_pixel_scale", {"shell": shell},
        )
        assert result["status"] == "changed"
        assert result["scale"] == 2
        assert result["previous"] == 1
        assert result["delta"] == 1
        assert shell._pixel_scale == 2

    def test_increase_clamps_at_max(self, router: ToolRouter) -> None:
        shell = SimpleNamespace(_pixel_scale=8)
        result = router.dispatch(
            "view.increase_pixel_scale", {"shell": shell},
        )
        assert result["status"] == "clamped"
        assert result["bound"] == "max"
        assert shell._pixel_scale == 8

    def test_decrease_from_two(self, router: ToolRouter) -> None:
        shell = SimpleNamespace(_pixel_scale=2)
        result = router.dispatch(
            "view.decrease_pixel_scale", {"shell": shell},
        )
        assert result["scale"] == 1
        assert result["delta"] == -1
        assert shell._pixel_scale == 1

    def test_decrease_clamps_at_min(self, router: ToolRouter) -> None:
        shell = SimpleNamespace(_pixel_scale=1)
        result = router.dispatch(
            "view.decrease_pixel_scale", {"shell": shell},
        )
        assert result["status"] == "clamped"
        assert result["bound"] == "min"
        assert shell._pixel_scale == 1

    def test_increase_no_shell_no_seed(self, router: ToolRouter) -> None:
        result = router.dispatch("view.increase_pixel_scale", {})
        assert result == {"status": "no_shell"}

    def test_decrease_no_shell_no_seed(self, router: ToolRouter) -> None:
        result = router.dispatch("view.decrease_pixel_scale", {})
        assert result == {"status": "no_shell"}

    def test_seed_wins_over_shell(self, router: ToolRouter) -> None:
        shell = SimpleNamespace(_pixel_scale=1)
        result = router.dispatch(
            "view.increase_pixel_scale",
            {"shell": shell, "scale": 3},
        )
        assert result["scale"] == 4
        assert result["previous"] == 3
        assert shell._pixel_scale == 4

    def test_fires_hook(self, router: ToolRouter) -> None:
        seen: list[int] = []
        shell = SimpleNamespace(
            _pixel_scale=1,
            _on_pixel_scale=lambda v: seen.append(v),
        )
        router.dispatch("view.increase_pixel_scale", {"shell": shell})
        assert seen == [2]

    def test_custom_max(self, router: ToolRouter) -> None:
        shell = SimpleNamespace(_pixel_scale=3)
        result = router.dispatch(
            "view.increase_pixel_scale",
            {"shell": shell, "max_scale": 3},
        )
        assert result["status"] == "clamped"


# ---------------------------------------------------------------------------
# spawn.stamp_repeat
# ---------------------------------------------------------------------------


class TestSpawnStampRepeat:
    def test_no_shell_no_last(self, router: ToolRouter) -> None:
        result = router.dispatch("spawn.stamp_repeat", {})
        assert result == {"status": "no_shell"}

    def test_no_history_with_shell(self, router: ToolRouter) -> None:
        shell = SimpleNamespace()
        result = router.dispatch(
            "spawn.stamp_repeat", {"shell": shell},
        )
        assert result == {"status": "no_history"}

    def test_zero_count(self, router: ToolRouter) -> None:
        shell = SimpleNamespace(
            _last_spawn=("rope", {"position": [0.0, 0.0, 0.0]}),
        )
        result = router.dispatch(
            "spawn.stamp_repeat", {"shell": shell, "count": 0},
        )
        assert result == {"status": "no_history"}

    def test_stamps_along_stride(self, router: ToolRouter) -> None:
        landed: list[tuple[str, dict]] = []
        shell = SimpleNamespace(
            _on_spawn=lambda cid, spec: landed.append((cid, spec)),
        )
        template = {"position": [0.0, 0.0, 0.0]}
        result = router.dispatch(
            "spawn.stamp_repeat",
            {
                "shell": shell,
                "last_spawn": ("rope", template),
                "count": 3,
                "stride": (2.0, 0.0, 0.0),
            },
        )
        assert result["status"] == "stamped"
        assert result["count"] == 3
        assert result["card_id"] == "rope"
        assert result["stride"] == (2.0, 0.0, 0.0)
        # x positions should march: 0, 2, 4
        xs = [spec["position"][0] for _, spec in landed]
        assert xs == [0.0, 2.0, 4.0]

    def test_jitter_deterministic_with_seed(
        self, router: ToolRouter,
    ) -> None:
        landed_a: list[dict] = []
        landed_b: list[dict] = []
        template = {"position": [0.0, 0.0, 0.0]}
        shell_a = SimpleNamespace(
            _on_spawn=lambda cid, spec: landed_a.append(spec),
        )
        shell_b = SimpleNamespace(
            _on_spawn=lambda cid, spec: landed_b.append(spec),
        )
        for shell, sink in ((shell_a, landed_a), (shell_b, landed_b)):
            router.dispatch(
                "spawn.stamp_repeat",
                {
                    "shell": shell,
                    "last_spawn": ("rope", template),
                    "count": 3,
                    "stride": (1.0, 0.0, 0.0),
                    "jitter": (0.5, 0.5, 0.0),
                    "seed": 12345,
                },
            )
        assert landed_a == landed_b
        # Verify jitter actually moved off the stride grid (probability
        # 1 for uniform(-0.5, 0.5) landing exactly on integers).
        xs = [spec["position"][0] for spec in landed_a]
        assert xs != [0.0, 1.0, 2.0]

    def test_records_stamp_history(self, router: ToolRouter) -> None:
        shell = SimpleNamespace()
        template = {"position": [0.0, 0.0, 0.0]}
        router.dispatch(
            "spawn.stamp_repeat",
            {
                "shell": shell,
                "last_spawn": ("humanoid", template),
                "count": 2,
                "stride": (3.0, 0.0, 0.0),
            },
        )
        history = getattr(shell, "_stamp_history", None)
        assert isinstance(history, list)
        assert len(history) == 1
        entry = history[0]
        assert entry["card_id"] == "humanoid"
        assert entry["count"] == 2
        assert len(entry["specs"]) == 2
