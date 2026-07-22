"""Tests for :mod:`pharos_editor.ui.theme.user_themes`.

The store exposes six responsibilities: bootstrap defaults, list baked
themes, list user themes, load (user-wins), save, revert, and
edit-detection. Every test uses ``tmp_path`` to isolate the user
directory so no test touches ``~/.pharos_engine`` on the developer
machine.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from pharos_editor.ui.theme.themes import TEENGIRL_NOTEBOOK
from pharos_editor.ui.theme.theme_spec import ThemeSpec
from pharos_editor.ui.theme.user_themes import (
    UserThemeError,
    UserThemeStore,
    bake_default_themes,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def baked_dir(tmp_path: Path) -> Path:
    """A fresh baked directory pre-populated with the six diary themes."""
    target = tmp_path / "baked"
    bake_default_themes(target)
    return target


@pytest.fixture()
def user_dir(tmp_path: Path) -> Path:
    """A fresh (missing) user directory. The store creates it on demand."""
    return tmp_path / "userthemes"


@pytest.fixture()
def store(user_dir: Path, baked_dir: Path) -> UserThemeStore:
    return UserThemeStore(user_dir=user_dir, baked_dir=baked_dir)


# ---------------------------------------------------------------------------
# Bake helper — sanity-checks the bake output first (feeds every fixture)
# ---------------------------------------------------------------------------


def test_bake_default_themes_writes_six_files(baked_dir: Path) -> None:
    files = sorted(p.name for p in baked_dir.iterdir())
    assert files == [
        "bullet_journal.theme.yaml",
        "cottagecore_garden.theme.yaml",
        "cozy_diary.theme.yaml",
        "kawaii_planner.theme.yaml",
        "scrapbook_summer.theme.yaml",
        "teengirl_notebook.theme.yaml",
    ]


def test_bake_default_themes_is_idempotent(baked_dir: Path) -> None:
    first = {p: p.read_bytes() for p in baked_dir.iterdir()}
    bake_default_themes(baked_dir)
    second = {p: p.read_bytes() for p in baked_dir.iterdir()}
    assert first == second


# ---------------------------------------------------------------------------
# Constructor + accessors
# ---------------------------------------------------------------------------


def test_store_defaults_point_at_home_dir() -> None:
    """The class-level defaults track the ``~/.pharos_engine/themes`` convention."""
    assert UserThemeStore.USER_DIR == Path.home() / ".pharos_engine" / "themes"
    # BAKED_DIR is co-located with the module.
    assert UserThemeStore.BAKED_DIR.name == "_baked"
    assert UserThemeStore.BAKED_DIR.parent.name == "themes"


def test_store_accepts_overrides(user_dir: Path, baked_dir: Path) -> None:
    s = UserThemeStore(user_dir=user_dir, baked_dir=baked_dir)
    assert s.user_dir == user_dir
    assert s.baked_dir == baked_dir


def test_store_rejects_bogus_paths() -> None:
    with pytest.raises((TypeError, ValueError)):
        UserThemeStore(user_dir=123)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# ensure_defaults_copied
# ---------------------------------------------------------------------------


def test_ensure_defaults_copies_missing_files(store: UserThemeStore) -> None:
    assert not store.user_dir.exists()
    copied = store.ensure_defaults_copied()
    assert set(copied) == set(store.list_baked())
    assert store.user_dir.is_dir()
    for name in store.list_baked():
        assert (store.user_dir / f"{name}.theme.yaml").is_file()


def test_ensure_defaults_is_idempotent(store: UserThemeStore) -> None:
    store.ensure_defaults_copied()
    second = store.ensure_defaults_copied()
    assert second == []


def test_ensure_defaults_does_not_overwrite_user_files(
    store: UserThemeStore,
) -> None:
    store.ensure_defaults_copied()
    user_file = store.user_dir / "teengirl_notebook.theme.yaml"
    user_file.write_text("# user-edited\nname: teengirl_notebook\n", encoding="utf-8")
    # Second bootstrap must not clobber the user edit.
    store.ensure_defaults_copied()
    text = user_file.read_text(encoding="utf-8")
    assert text.startswith("# user-edited")


def test_ensure_defaults_recovers_missing_baked_file_on_user_side(
    store: UserThemeStore,
) -> None:
    store.ensure_defaults_copied()
    # Simulate the user accidentally deleting a file.
    (store.user_dir / "cozy_diary.theme.yaml").unlink()
    copied = store.ensure_defaults_copied()
    assert copied == ["cozy_diary"]
    assert (store.user_dir / "cozy_diary.theme.yaml").is_file()


def test_ensure_defaults_creates_missing_user_dir(
    tmp_path: Path, baked_dir: Path,
) -> None:
    user_dir = tmp_path / "does" / "not" / "exist"
    s = UserThemeStore(user_dir=user_dir, baked_dir=baked_dir)
    s.ensure_defaults_copied()
    assert user_dir.is_dir()


# ---------------------------------------------------------------------------
# Listing
# ---------------------------------------------------------------------------


def test_list_baked_returns_six_defaults(store: UserThemeStore) -> None:
    baked = store.list_baked()
    assert len(baked) == 6
    assert "teengirl_notebook" in baked
    assert "cozy_diary" in baked
    assert "bullet_journal" in baked
    assert "scrapbook_summer" in baked
    assert "cottagecore_garden" in baked
    assert "kawaii_planner" in baked


def test_list_user_empty_before_bootstrap(store: UserThemeStore) -> None:
    assert store.list_user() == []


def test_list_user_populated_after_bootstrap(store: UserThemeStore) -> None:
    store.ensure_defaults_copied()
    assert set(store.list_user()) == set(store.list_baked())


def test_listing_ignores_non_theme_files(store: UserThemeStore) -> None:
    store.ensure_defaults_copied()
    # Sprinkle unrelated files that should be ignored.
    (store.user_dir / "README.md").write_text("noise", encoding="utf-8")
    (store.user_dir / "unrelated.yaml").write_text("noise", encoding="utf-8")
    assert set(store.list_user()) == set(store.list_baked())


# ---------------------------------------------------------------------------
# Load
# ---------------------------------------------------------------------------


def test_load_theme_reads_from_user_first(store: UserThemeStore) -> None:
    store.ensure_defaults_copied()
    theme = store.load_theme("teengirl_notebook")
    assert isinstance(theme, ThemeSpec)
    assert theme.name == "teengirl_notebook"


def test_load_theme_falls_back_to_baked(store: UserThemeStore) -> None:
    # No bootstrap — user dir is empty; baked file is the only source.
    theme = store.load_theme("cozy_diary")
    assert isinstance(theme, ThemeSpec)
    assert theme.name == "cozy_diary"


def test_load_theme_user_wins_over_baked(store: UserThemeStore) -> None:
    """Edits to a user file must appear on next load."""
    store.ensure_defaults_copied()
    user_path = store.user_dir / "teengirl_notebook.theme.yaml"
    original = ThemeSpec.from_yaml(user_path.read_text(encoding="utf-8"))
    # Change the metadata (a safe round-trippable edit).
    original.metadata["edited_marker"] = "42"
    store.save_theme(original, "teengirl_notebook")
    reloaded = store.load_theme("teengirl_notebook")
    assert reloaded.metadata.get("edited_marker") == "42"


def test_load_theme_unknown_name_raises(store: UserThemeStore) -> None:
    with pytest.raises(UserThemeError):
        store.load_theme("does_not_exist")


def test_load_theme_corrupt_yaml_raises_clean_error(
    store: UserThemeStore,
) -> None:
    store.ensure_defaults_copied()
    user_path = store.user_dir / "cozy_diary.theme.yaml"
    user_path.write_text("::: not valid yaml :::\n{{{", encoding="utf-8")
    with pytest.raises(UserThemeError) as exc:
        store.load_theme("cozy_diary")
    # The offending path is inside the error message.
    assert "cozy_diary" in str(exc.value)


def test_load_theme_rejects_empty_name(store: UserThemeStore) -> None:
    with pytest.raises((TypeError, ValueError)):
        store.load_theme("")


# ---------------------------------------------------------------------------
# Save
# ---------------------------------------------------------------------------


def test_save_theme_writes_yaml_file(store: UserThemeStore) -> None:
    path = store.save_theme(TEENGIRL_NOTEBOOK)
    assert path == store.user_dir / "teengirl_notebook.theme.yaml"
    assert path.is_file()
    text = path.read_text(encoding="utf-8")
    assert "teengirl_notebook" in text


def test_save_theme_roundtrips_through_load(store: UserThemeStore) -> None:
    store.save_theme(TEENGIRL_NOTEBOOK)
    reloaded = store.load_theme("teengirl_notebook")
    assert reloaded.name == "teengirl_notebook"
    # Every palette key survives.
    assert set(reloaded.palette) == set(TEENGIRL_NOTEBOOK.palette)


def test_save_theme_accepts_rename_via_name_argument(
    store: UserThemeStore,
) -> None:
    path = store.save_theme(TEENGIRL_NOTEBOOK, name="my_custom_notebook")
    assert path == store.user_dir / "my_custom_notebook.theme.yaml"
    assert path.is_file()


def test_save_theme_rejects_non_theme_input(store: UserThemeStore) -> None:
    with pytest.raises(TypeError):
        store.save_theme("not a theme")  # type: ignore[arg-type]


def test_save_theme_is_atomic_no_partial_file(
    store: UserThemeStore, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A crash mid-write must not leave a partial file behind."""
    original_replace = os.replace

    def _boom(src: str, dst: str) -> None:
        raise OSError("simulated crash before replace")

    monkeypatch.setattr(os, "replace", _boom)
    with pytest.raises(OSError):
        store.save_theme(TEENGIRL_NOTEBOOK)
    # No final file, no orphan .tmp lying around under a *.theme.yaml name.
    monkeypatch.setattr(os, "replace", original_replace)
    assert not (store.user_dir / "teengirl_notebook.theme.yaml").exists()


# ---------------------------------------------------------------------------
# Revert
# ---------------------------------------------------------------------------


def test_revert_to_baked_overwrites_user_file(store: UserThemeStore) -> None:
    store.ensure_defaults_copied()
    user_path = store.user_dir / "teengirl_notebook.theme.yaml"
    user_path.write_text("# corrupted\nname: teengirl_notebook\n", encoding="utf-8")
    store.revert_to_baked("teengirl_notebook")
    text = user_path.read_text(encoding="utf-8")
    assert "corrupted" not in text
    baked_text = (store.baked_dir / "teengirl_notebook.theme.yaml").read_text(
        encoding="utf-8",
    )
    assert text == baked_text


def test_revert_to_baked_creates_user_file_when_missing(
    store: UserThemeStore,
) -> None:
    # No bootstrap first — user dir empty.
    store.revert_to_baked("bullet_journal")
    assert (store.user_dir / "bullet_journal.theme.yaml").is_file()


def test_revert_to_baked_unknown_theme_raises(store: UserThemeStore) -> None:
    with pytest.raises(UserThemeError):
        store.revert_to_baked("no_such_theme")


# ---------------------------------------------------------------------------
# is_edited
# ---------------------------------------------------------------------------


def test_is_edited_false_after_bootstrap(store: UserThemeStore) -> None:
    store.ensure_defaults_copied()
    for name in store.list_baked():
        assert store.is_edited(name) is False


def test_is_edited_true_after_user_change(store: UserThemeStore) -> None:
    store.ensure_defaults_copied()
    user_path = store.user_dir / "teengirl_notebook.theme.yaml"
    user_path.write_text(
        user_path.read_text(encoding="utf-8") + "\n# extra\n",
        encoding="utf-8",
    )
    assert store.is_edited("teengirl_notebook") is True
    # Sibling themes are still clean.
    assert store.is_edited("cozy_diary") is False


def test_is_edited_false_when_user_file_missing(
    store: UserThemeStore,
) -> None:
    # No bootstrap — baked exists but user file does not.
    assert store.is_edited("cozy_diary") is False


def test_is_edited_returns_to_false_after_revert(
    store: UserThemeStore,
) -> None:
    store.ensure_defaults_copied()
    user_path = store.user_dir / "kawaii_planner.theme.yaml"
    user_path.write_text("changed", encoding="utf-8")
    assert store.is_edited("kawaii_planner") is True
    store.revert_to_baked("kawaii_planner")
    assert store.is_edited("kawaii_planner") is False


# ---------------------------------------------------------------------------
# watch_user_dir (optional; guarded so the suite still runs without watchdog)
# ---------------------------------------------------------------------------


def test_watch_user_dir_returns_none_without_watchdog(
    store: UserThemeStore, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When watchdog is not importable, the watcher must degrade to None."""
    import builtins

    real_import = builtins.__import__

    def _fake_import(name: str, *args: object, **kwargs: object):  # noqa: ANN401
        if name.startswith("watchdog"):
            raise ImportError("watchdog stubbed out")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _fake_import)
    observer = store.watch_user_dir()
    assert observer is None


# ---------------------------------------------------------------------------
# Full YAML round-trip through the store
# ---------------------------------------------------------------------------


def test_full_roundtrip_preserves_theme_content(
    store: UserThemeStore,
) -> None:
    """Save → load returns a theme whose to_yaml matches the input."""
    store.save_theme(TEENGIRL_NOTEBOOK)
    reloaded = store.load_theme("teengirl_notebook")
    assert reloaded.to_yaml() == TEENGIRL_NOTEBOOK.to_yaml()


def test_bake_default_themes_baked_files_load(baked_dir: Path) -> None:
    """Every baked file must parse back into a valid ThemeSpec."""
    for path in baked_dir.iterdir():
        theme = ThemeSpec.from_yaml(path.read_text(encoding="utf-8"))
        assert theme.name == path.name.removesuffix(".theme.yaml")
