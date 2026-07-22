"""Tests for :mod:`pharos_engine.ui.editor.file_drop_handler` (EE4).

Covers classification per extension, dispatch semantics, batch
robustness (one failure doesn't abort the whole drop), and default
handler wiring against real engine subsystems (PrefabLibrary,
UserThemeStore, on-disk copies for shaders / images).
"""
from __future__ import annotations

import types
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from pharos_engine.ui.editor.file_drop_handler import (
    COMPOUND_SUFFIX_MAP,
    DEFAULT_SHADER_DIR,
    DropAction,
    DropHandlerResult,
    FileDropEvent,
    FileDropHandler,
    SINGLE_SUFFIX_MAP,
    default_handlers,
    make_default_handler,
)


# ---------------------------------------------------------------------------
# Small fixtures.
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_files(tmp_path: Path) -> dict[str, Path]:
    """Return a dict of representative files touching every route."""
    files = {
        "prefab": tmp_path / "widget.prefab.yaml",
        "theme_yaml": tmp_path / "moody.theme.yaml",
        "theme_css": tmp_path / "moody.theme.css",
        "wgsl": tmp_path / "outline.wgsl",
        "glsl": tmp_path / "outline.glsl",
        "png": tmp_path / "sprite.png",
        "jpg": tmp_path / "background.jpg",
        "webp": tmp_path / "compressed.webp",
        "script": tmp_path / "logic.py",
        "unknown_txt": tmp_path / "notes.txt",
        "unknown_bin": tmp_path / "data.bin",
        "no_ext": tmp_path / "READMELESS",
    }
    for path in files.values():
        path.write_text("stub", encoding="utf-8")
    return files


def _event(paths: list[Path], pos: tuple[float, float] = (0.0, 0.0)) -> FileDropEvent:
    return FileDropEvent(paths=list(paths), drop_position=pos, modifier_keys=set())


# ---------------------------------------------------------------------------
# classify() coverage.
# ---------------------------------------------------------------------------


def test_classify_prefab(tmp_files: dict[str, Path]) -> None:
    assert FileDropHandler.classify(tmp_files["prefab"]) is DropAction.PREFAB_SPAWN


def test_classify_theme_yaml(tmp_files: dict[str, Path]) -> None:
    assert (
        FileDropHandler.classify(tmp_files["theme_yaml"])
        is DropAction.THEME_INSTALL
    )


def test_classify_theme_css(tmp_files: dict[str, Path]) -> None:
    assert (
        FileDropHandler.classify(tmp_files["theme_css"])
        is DropAction.THEME_INSTALL
    )


def test_classify_wgsl(tmp_files: dict[str, Path]) -> None:
    assert (
        FileDropHandler.classify(tmp_files["wgsl"])
        is DropAction.SHADER_INSTALL
    )


def test_classify_glsl(tmp_files: dict[str, Path]) -> None:
    assert (
        FileDropHandler.classify(tmp_files["glsl"])
        is DropAction.SHADER_INSTALL
    )


def test_classify_png(tmp_files: dict[str, Path]) -> None:
    assert FileDropHandler.classify(tmp_files["png"]) is DropAction.IMAGE_IMPORT


def test_classify_jpg(tmp_files: dict[str, Path]) -> None:
    assert FileDropHandler.classify(tmp_files["jpg"]) is DropAction.IMAGE_IMPORT


def test_classify_webp(tmp_files: dict[str, Path]) -> None:
    assert FileDropHandler.classify(tmp_files["webp"]) is DropAction.IMAGE_IMPORT


def test_classify_script(tmp_files: dict[str, Path]) -> None:
    assert FileDropHandler.classify(tmp_files["script"]) is DropAction.SCRIPT_ATTACH


def test_classify_unknown_txt(tmp_files: dict[str, Path]) -> None:
    assert FileDropHandler.classify(tmp_files["unknown_txt"]) is DropAction.REJECTED


def test_classify_unknown_bin(tmp_files: dict[str, Path]) -> None:
    assert FileDropHandler.classify(tmp_files["unknown_bin"]) is DropAction.REJECTED


def test_classify_no_extension(tmp_files: dict[str, Path]) -> None:
    assert FileDropHandler.classify(tmp_files["no_ext"]) is DropAction.REJECTED


def test_classify_case_insensitive(tmp_path: Path) -> None:
    # Drops from Windows Explorer arrive with uppercase extensions.
    upper = tmp_path / "SPRITE.PNG"
    upper.write_text("x", encoding="utf-8")
    assert FileDropHandler.classify(upper) is DropAction.IMAGE_IMPORT

    upper_prefab = tmp_path / "Robot.PREFAB.YAML"
    upper_prefab.write_text("x", encoding="utf-8")
    assert (
        FileDropHandler.classify(upper_prefab) is DropAction.PREFAB_SPAWN
    )


def test_classify_accepts_str_path() -> None:
    assert FileDropHandler.classify("thing.wgsl") is DropAction.SHADER_INSTALL
    assert FileDropHandler.classify("thing.txt") is DropAction.REJECTED


def test_classify_prefab_beats_plain_yaml(tmp_path: Path) -> None:
    # Plain ``.yaml`` isn't a valid drop target — the compound suffix
    # must win but a bare ``.yaml`` still rejects.
    plain = tmp_path / "config.yaml"
    plain.write_text("x", encoding="utf-8")
    assert FileDropHandler.classify(plain) is DropAction.REJECTED


def test_reject_reason_includes_extension() -> None:
    reason = FileDropHandler.reject_reason(Path("weird.xyz"))
    assert "xyz" in reason.lower()
    assert "weird.xyz" in reason


# ---------------------------------------------------------------------------
# register_handler + has_handler.
# ---------------------------------------------------------------------------


def test_register_handler_rejects_non_action() -> None:
    handler = FileDropHandler()
    with pytest.raises(TypeError):
        handler.register_handler("not-an-enum", lambda p, e, c: None)  # type: ignore[arg-type]


def test_register_handler_rejects_rejected_action() -> None:
    handler = FileDropHandler()
    with pytest.raises(ValueError):
        handler.register_handler(DropAction.REJECTED, lambda p, e, c: None)


def test_register_handler_rejects_non_callable() -> None:
    handler = FileDropHandler()
    with pytest.raises(TypeError):
        handler.register_handler(DropAction.PREFAB_SPAWN, "not-callable")  # type: ignore[arg-type]


def test_register_handler_overrides_previous() -> None:
    handler = FileDropHandler()
    a = lambda p, e, c: None  # noqa: E731
    b = lambda p, e, c: None  # noqa: E731
    handler.register_handler(DropAction.PREFAB_SPAWN, a)
    handler.register_handler(DropAction.PREFAB_SPAWN, b)
    assert handler._handlers[DropAction.PREFAB_SPAWN] is b


def test_has_handler_and_registered_actions() -> None:
    handler = FileDropHandler()
    assert not handler.has_handler(DropAction.PREFAB_SPAWN)
    assert handler.registered_actions() == set()
    handler.register_handler(DropAction.PREFAB_SPAWN, lambda p, e, c: None)
    assert handler.has_handler(DropAction.PREFAB_SPAWN)
    assert handler.registered_actions() == {DropAction.PREFAB_SPAWN}


# ---------------------------------------------------------------------------
# handle_drop dispatch.
# ---------------------------------------------------------------------------


def test_handle_drop_invokes_correct_handler(tmp_files: dict[str, Path]) -> None:
    seen: list[tuple[str, Path]] = []
    handler = FileDropHandler()

    def _prefab(p, e, c):
        seen.append(("prefab", p))

    def _theme(p, e, c):
        seen.append(("theme", p))

    handler.register_handler(DropAction.PREFAB_SPAWN, _prefab)
    handler.register_handler(DropAction.THEME_INSTALL, _theme)

    event = _event([tmp_files["prefab"], tmp_files["theme_yaml"]])
    results = handler.handle_drop(event, ctx=None)

    assert [kind for kind, _ in seen] == ["prefab", "theme"]
    assert all(r.success for r in results)
    assert [r.action for r in results] == [
        DropAction.PREFAB_SPAWN,
        DropAction.THEME_INSTALL,
    ]


def test_handle_drop_missing_handler_rejects(tmp_files: dict[str, Path]) -> None:
    handler = FileDropHandler()
    # PREFAB_SPAWN is intentionally NOT registered.
    event = _event([tmp_files["prefab"]])
    results = handler.handle_drop(event, ctx=None)
    assert len(results) == 1
    assert results[0].action is DropAction.REJECTED
    assert not results[0].success
    assert "no handler registered" in results[0].error.lower()


def test_handle_drop_unknown_rejected_with_reason(
    tmp_files: dict[str, Path],
) -> None:
    handler = FileDropHandler()
    event = _event([tmp_files["unknown_txt"]])
    results = handler.handle_drop(event, ctx=None)
    assert results[0].action is DropAction.REJECTED
    assert not results[0].success
    assert results[0].error  # reason string not empty
    assert "txt" in results[0].error.lower()


def test_handle_drop_multi_file_dispatch(tmp_files: dict[str, Path]) -> None:
    seen: list[str] = []
    handler = FileDropHandler()
    handler.register_handler(
        DropAction.IMAGE_IMPORT, lambda p, e, c: seen.append(f"img:{p.name}"),
    )
    handler.register_handler(
        DropAction.SHADER_INSTALL, lambda p, e, c: seen.append(f"sh:{p.name}"),
    )
    handler.register_handler(
        DropAction.SCRIPT_ATTACH, lambda p, e, c: seen.append(f"py:{p.name}"),
    )
    event = _event(
        [
            tmp_files["png"],
            tmp_files["wgsl"],
            tmp_files["script"],
            tmp_files["unknown_bin"],
        ]
    )
    results = handler.handle_drop(event, ctx=None)
    assert len(results) == 4
    # Three succeed, one rejects.
    successes = [r for r in results if r.success]
    failures = [r for r in results if not r.success]
    assert len(successes) == 3
    assert len(failures) == 1
    assert failures[0].action is DropAction.REJECTED


def test_handle_drop_one_failure_does_not_abort(
    tmp_files: dict[str, Path],
) -> None:
    seen: list[str] = []
    handler = FileDropHandler()

    def _boom(p, e, c):
        raise RuntimeError("boom")

    def _ok(p, e, c):
        seen.append(p.name)

    handler.register_handler(DropAction.PREFAB_SPAWN, _boom)
    handler.register_handler(DropAction.IMAGE_IMPORT, _ok)

    event = _event(
        [
            tmp_files["prefab"],  # will raise
            tmp_files["png"],     # should still run
        ]
    )
    results = handler.handle_drop(event, ctx=None)
    assert seen == ["sprite.png"]  # second file still processed
    assert results[0].success is False
    assert "RuntimeError" in results[0].error
    assert "boom" in results[0].error
    assert results[1].success is True


def test_handle_drop_empty_paths(tmp_path: Path) -> None:
    handler = FileDropHandler()
    event = FileDropEvent(paths=[], drop_position=(0.0, 0.0))
    results = handler.handle_drop(event, ctx=None)
    assert results == []


def test_handle_drop_type_error_on_wrong_event() -> None:
    handler = FileDropHandler()
    with pytest.raises(TypeError):
        handler.handle_drop("not-an-event")  # type: ignore[arg-type]


def test_handle_drop_context_is_passed(tmp_files: dict[str, Path]) -> None:
    seen_ctx: list[Any] = []
    handler = FileDropHandler()  # noqa
    handler.register_handler(
        DropAction.IMAGE_IMPORT,
        lambda p, e, c: seen_ctx.append(c),
    )
    ctx = SimpleNamespace(project_root=Path("/tmp/project"))
    event = _event([tmp_files["png"]])
    handler.handle_drop(event, ctx=ctx)
    assert seen_ctx == [ctx]


def test_on_file_drop_wraps_flat_signature(tmp_files: dict[str, Path]) -> None:
    seen_positions: list[tuple[float, float]] = []
    handler = FileDropHandler()
    handler.register_handler(
        DropAction.IMAGE_IMPORT,
        lambda p, e, c: seen_positions.append(e.drop_position),
    )
    results = handler.on_file_drop(
        [tmp_files["png"]],
        (12.5, 34.75),
        modifiers=["Shift"],
    )
    assert seen_positions == [(12.5, 34.75)]
    assert results[0].success


# ---------------------------------------------------------------------------
# Event validation.
# ---------------------------------------------------------------------------


def test_event_normalises_paths_and_modifiers(tmp_files: dict[str, Path]) -> None:
    event = FileDropEvent(
        paths=[str(tmp_files["png"])],  # str, not Path
        drop_position=(1, 2),  # ints
        modifier_keys={"Shift", "CTRL"},
    )
    assert all(isinstance(p, Path) for p in event.paths)
    assert event.drop_position == (1.0, 2.0)
    assert event.modifier_keys == {"shift", "ctrl"}


def test_event_rejects_bad_position() -> None:
    with pytest.raises((TypeError, ValueError)):
        FileDropEvent(paths=[], drop_position=(0.0, 0.0, 0.0))  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# default_handlers wiring — smoke tests using real subsystems.
# ---------------------------------------------------------------------------


def test_default_handlers_registers_all_actions() -> None:
    handler = FileDropHandler(handlers=default_handlers())
    for action in DropAction:
        if action is DropAction.REJECTED:
            continue
        assert handler.has_handler(action), action


def test_make_default_handler_shorthand() -> None:
    handler = make_default_handler()
    for action in DropAction:
        if action is DropAction.REJECTED:
            continue
        assert handler.has_handler(action)


def test_default_shader_handler_copies_to_dir(tmp_path: Path) -> None:
    src = tmp_path / "outline.wgsl"
    src.write_text("// wgsl body", encoding="utf-8")
    shader_dir = tmp_path / "shaders"
    ctx = SimpleNamespace(shader_dir=shader_dir)
    handler = make_default_handler()
    results = handler.handle_drop(_event([src]), ctx=ctx)
    assert results[0].success, results[0].error
    assert (shader_dir / "outline.wgsl").read_text(encoding="utf-8") == "// wgsl body"


def test_default_image_handler_copies_to_project_textures(tmp_path: Path) -> None:
    src = tmp_path / "sprite.png"
    src.write_bytes(b"\x89PNG\r\n\x1a\n")
    project = tmp_path / "proj"
    ctx = SimpleNamespace(project_root=project)
    handler = make_default_handler()
    results = handler.handle_drop(_event([src]), ctx=ctx)
    assert results[0].success, results[0].error
    dest = project / "assets" / "textures" / "sprite.png"
    assert dest.exists()
    assert dest.read_bytes() == b"\x89PNG\r\n\x1a\n"


def test_default_image_handler_fails_without_project_root(tmp_path: Path) -> None:
    src = tmp_path / "sprite.png"
    src.write_bytes(b"x")
    handler = make_default_handler()
    results = handler.handle_drop(_event([src]), ctx=SimpleNamespace())
    assert not results[0].success
    assert "project_root" in results[0].error


def test_default_theme_handler_copies_into_user_theme_store(tmp_path: Path) -> None:
    src = tmp_path / "midnight.theme.yaml"
    src.write_text("name: midnight\n", encoding="utf-8")
    theme_dir = tmp_path / "themes"
    store = SimpleNamespace(_user_dir=theme_dir)
    ctx = SimpleNamespace(user_theme_store=store)
    handler = make_default_handler()
    results = handler.handle_drop(_event([src]), ctx=ctx)
    assert results[0].success, results[0].error
    assert (theme_dir / "midnight.theme.yaml").read_text(encoding="utf-8") == (
        "name: midnight\n"
    )


def test_default_prefab_handler_registers_and_spawns(tmp_path: Path) -> None:
    from pharos_engine.prefabs import Prefab, PrefabLibrary

    prefab = Prefab(
        name="drop_test_circle",
        category="props",
        body_spec={"kind": "circle", "radius": 1.0},
    )
    src = tmp_path / "drop_test_circle.prefab.yaml"
    src.write_text(prefab.to_yaml(), encoding="utf-8")

    library = PrefabLibrary()
    spawned: list[tuple[str, tuple[float, float]]] = []

    class _StubWorld:
        pass

    # Monkey-patch ``spawn`` on the library to sidestep the full
    # Body/World construction chain — the drop handler's contract is
    # only that it calls ``library.spawn(name, world, position)``.
    def _spawn(name, world, position, rotation=0.0):
        spawned.append((name, position))
        return []

    library.spawn = _spawn  # type: ignore[assignment]
    ctx = SimpleNamespace(prefab_library=library, world=_StubWorld())
    handler = make_default_handler()
    results = handler.handle_drop(_event([src], pos=(4.0, 5.0)), ctx=ctx)
    assert results[0].success, results[0].error
    assert "drop_test_circle" in library
    assert spawned == [("drop_test_circle", (4.0, 5.0))]


def test_default_script_handler_toasts_without_selection(tmp_path: Path) -> None:
    src = tmp_path / "logic.py"
    src.write_text("print('hi')", encoding="utf-8")
    toasts: list[str] = []
    ctx = SimpleNamespace(
        selected_entity=None,
        toast=lambda msg: toasts.append(msg),
    )
    handler = make_default_handler()
    results = handler.handle_drop(_event([src]), ctx=ctx)
    # Toast path succeeds (no exception) — the handler returned normally.
    assert results[0].success, results[0].error
    assert len(toasts) == 1
    assert "logic.py" in toasts[0]


def test_default_script_handler_attaches_via_attach_script(tmp_path: Path) -> None:
    src = tmp_path / "logic.py"
    src.write_text("print('hi')", encoding="utf-8")

    attached: list[Path] = []

    class _Entity:
        def attach_script(self, path: Path) -> None:
            attached.append(Path(path))

    ctx = SimpleNamespace(selected_entity=_Entity())
    handler = make_default_handler()
    results = handler.handle_drop(_event([src]), ctx=ctx)
    assert results[0].success, results[0].error
    assert attached == [src]


def test_default_script_handler_sets_script_path_fallback(tmp_path: Path) -> None:
    src = tmp_path / "logic.py"
    src.write_text("print('hi')", encoding="utf-8")

    class _Entity:
        script_path: Path | None = None

    entity = _Entity()
    ctx = SimpleNamespace(selected_entity=entity)
    handler = make_default_handler()
    results = handler.handle_drop(_event([src]), ctx=ctx)
    assert results[0].success, results[0].error
    assert entity.script_path == src


# ---------------------------------------------------------------------------
# Module-level constants — sanity.
# ---------------------------------------------------------------------------


def test_extension_maps_are_disjoint() -> None:
    # ``.yaml`` alone must not be in the single-suffix map (otherwise
    # it would swallow ``.prefab.yaml``).
    assert ".yaml" not in SINGLE_SUFFIX_MAP
    # The compound map uses ``.<kind>.<ext>`` shape.
    for key in COMPOUND_SUFFIX_MAP:
        assert key.count(".") >= 2, key


def test_default_shader_dir_is_under_home() -> None:
    assert DEFAULT_SHADER_DIR.is_absolute()
    assert "pharos_engine" in str(DEFAULT_SHADER_DIR).lower()

