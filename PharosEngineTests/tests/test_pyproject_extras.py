"""Regression tests for ``pyproject.toml`` extras structure (II6).

Locks in the extras contract landed 2026-07-05:

* Every expected extra must be declared.
* Base ``[project.dependencies]`` must stay minimal — no torch, no
  opencv, no dearpygui, no editor stack.
* The ``all`` meta-extra references every sub-extra except heavy
  ones (``ai`` — 800 MB torch + transformers bundle).
* The ``dev`` extra includes pytest + maturin.
* The package name is spelled ``pharos-engine`` (hyphen, not
  underscore, matches PyPI + install command).

See ``docs/pyproject_extras_2026_07_05.md`` for the rationale and
install matrix. See ``docs/nova3d_gap_audit_2026_07_05.md`` for the
HH3 recommendation this test suite verifies.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - CI runs 3.11+
    import tomli as tomllib  # type: ignore[import-not-found]

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
PYPROJECT_PATH = REPO_ROOT / "pyproject.toml"


@pytest.fixture(scope="module")
def pyproject() -> dict[str, Any]:
    """Parse and cache pyproject.toml for the module."""
    assert PYPROJECT_PATH.exists(), f"pyproject.toml missing at {PYPROJECT_PATH}"
    with PYPROJECT_PATH.open("rb") as fp:
        return tomllib.load(fp)


@pytest.fixture(scope="module")
def extras(pyproject: dict[str, Any]) -> dict[str, list[str]]:
    """Extract [project.optional-dependencies] as a plain dict."""
    proj = pyproject["project"]
    return dict(proj.get("optional-dependencies", {}))


@pytest.fixture(scope="module")
def base_deps(pyproject: dict[str, Any]) -> list[str]:
    return list(pyproject["project"].get("dependencies", []))


# ---------------------------------------------------------------------------
# 1. Package identity + parseability
# ---------------------------------------------------------------------------


def test_pyproject_parses(pyproject: dict[str, Any]) -> None:
    """pyproject.toml must be valid TOML with a [project] table."""
    assert "project" in pyproject
    assert "build-system" in pyproject


def test_package_name_is_pharos_engine(pyproject: dict[str, Any]) -> None:
    """Package name must be ``pharos-engine`` (hyphenated, matches PyPI)."""
    assert pyproject["project"]["name"] == "pharos-engine"


def test_build_system_uses_maturin(pyproject: dict[str, Any]) -> None:
    """maturin backend must remain — the Rust ``_core`` wheel depends on it."""
    build = pyproject["build-system"]
    assert build["build-backend"] == "maturin"
    assert any("maturin" in req for req in build["requires"])


def test_maturin_config_preserved(pyproject: dict[str, Any]) -> None:
    """[tool.maturin] must survive the II6 edit — includes / excludes matter."""
    tool = pyproject.get("tool", {})
    maturin_cfg = tool.get("maturin", {})
    assert maturin_cfg.get("python-source") == "python"
    assert maturin_cfg.get("module-name") == "pharos_engine._core"


# ---------------------------------------------------------------------------
# 2. Every expected extra is declared
# ---------------------------------------------------------------------------

EXPECTED_EXTRAS = {
    "editor",
    "assets",
    "hud",
    "math",
    "video",
    "audio",
    "network",
    "ai",
    "dev",
    "3d",
    "all",
}


def test_all_expected_extras_declared(extras: dict[str, list[str]]) -> None:
    """Every extra HH3 recommended must exist."""
    missing = EXPECTED_EXTRAS - set(extras)
    assert not missing, f"Missing extras: {sorted(missing)}"


def test_no_extras_dropped(extras: dict[str, list[str]]) -> None:
    """Existing pre-II6 extras must never be silently removed."""
    pre_ii6 = {"editor", "video", "audio", "dev", "ai", "math", "network", "3d"}
    dropped = pre_ii6 - set(extras)
    assert not dropped, f"Regression — dropped extras: {sorted(dropped)}"


# ---------------------------------------------------------------------------
# 3. Per-extra content assertions
# ---------------------------------------------------------------------------


def test_assets_extra_has_mesh_and_image_importers(extras: dict[str, list[str]]) -> None:
    """assets = pygltflib + trimesh + imageio + Pillow (HH3 §6.5)."""
    assets = " ".join(extras["assets"]).lower()
    assert "pygltflib" in assets
    assert "trimesh" in assets
    assert "imageio" in assets
    assert "pillow" in assets


def test_editor_extra_has_dearpygui(extras: dict[str, list[str]]) -> None:
    """editor extra must retain dearpygui — the whole notebook UI depends on it."""
    editor = " ".join(extras["editor"]).lower()
    assert "dearpygui" in editor


def test_hud_extra_uses_imgui(extras: dict[str, list[str]]) -> None:
    """hud extra must use imgui[glfw] (HH3 §7.2 recommendation)."""
    hud = " ".join(extras["hud"]).lower()
    assert "imgui" in hud


def test_math_extra_has_arithma(extras: dict[str, list[str]]) -> None:
    """math extra must keep arithma — the Formula backend."""
    math = " ".join(extras["math"]).lower()
    assert "arithma" in math


def test_video_extra_has_opencv_and_ffmpeg(extras: dict[str, list[str]]) -> None:
    """video extra grew opencv-python + imageio-ffmpeg alongside existing av."""
    video = " ".join(extras["video"]).lower()
    assert "opencv-python" in video
    assert "imageio-ffmpeg" in video


def test_audio_extra_has_backends(extras: dict[str, list[str]]) -> None:
    """audio extra must include sounddevice + pyaudio (soundfile stays too)."""
    audio = " ".join(extras["audio"]).lower()
    assert "sounddevice" in audio
    assert "pyaudio" in audio


def test_ai_extra_has_torch_and_transformers(extras: dict[str, list[str]]) -> None:
    """ai extra ships torch + transformers for HuggingFace pipelines."""
    ai = " ".join(extras["ai"]).lower()
    assert "torch" in ai
    assert "transformers" in ai


def test_network_extra_has_websockets(extras: dict[str, list[str]]) -> None:
    """network extra now includes websockets for signalling / lobby."""
    net = " ".join(extras["network"]).lower()
    assert "websockets" in net
    # Existing DHT + WebRTC + LAN deps must survive.
    assert "kademlia" in net
    assert "aioice" in net
    assert "zeroconf" in net


def test_dev_extra_has_pytest_and_maturin(extras: dict[str, list[str]]) -> None:
    """dev extra must include pytest + maturin for CI + Rust wheel builds."""
    dev = " ".join(extras["dev"]).lower()
    assert "pytest" in dev
    assert "maturin" in dev


# ---------------------------------------------------------------------------
# 4. Meta-extra: `all`
# ---------------------------------------------------------------------------


def test_all_extra_references_sub_extras(extras: dict[str, list[str]]) -> None:
    """`all` must reference the sub-extras via PEP 508 self-dep syntax."""
    all_entries = extras["all"]
    assert len(all_entries) >= 1
    joined = " ".join(all_entries).lower()
    # Must be a pharos-engine[...] self-reference, not a flat pkg list.
    assert "pharos-engine[" in joined


def test_all_extra_omits_ai(extras: dict[str, list[str]]) -> None:
    """`all` must NOT pull in the ~800 MB torch/transformers bundle.

    HH3 §8.2: ``ai`` stays opt-in. Users who want it must ask
    explicitly via ``pip install pharos-engine[all,ai]``.
    """
    joined = " ".join(extras["all"]).lower()
    # The token ",ai," or "[ai," or ",ai]" would indicate ai leaked in.
    assert "ai," not in joined
    assert ",ai]" not in joined
    assert "[ai" not in joined
    assert "ai," not in joined


def test_all_extra_includes_expected_sub_extras(extras: dict[str, list[str]]) -> None:
    """`all` must include editor + assets + hud + math + video + audio + network."""
    joined = " ".join(extras["all"]).lower()
    for sub in ("editor", "assets", "hud", "math", "video", "audio", "network"):
        assert sub in joined, f"`all` extra missing reference to `{sub}`"


# ---------------------------------------------------------------------------
# 5. Base deps stay minimal
# ---------------------------------------------------------------------------


def test_base_deps_are_minimal(base_deps: list[str]) -> None:
    """Base deps must not include heavy libs — those live in extras."""
    joined = " ".join(base_deps).lower()
    forbidden = [
        "torch",
        "transformers",
        "opencv-python",
        "dearpygui",
        "pygltflib",
        "trimesh",
        "imgui",
        "pyaudio",
        "sounddevice",
        "av>=",  # PyAV — belongs in `video`
        "kademlia",
        "aioice",
        "arithma",
    ]
    for pkg in forbidden:
        assert pkg not in joined, (
            f"Base dependency `{pkg}` leaked from an extra. "
            "Base install must stay lean (< 15 MB)."
        )


def test_base_deps_contain_core_libs(base_deps: list[str]) -> None:
    """Base deps must still carry wgpu / numpy / Pillow / glfw / pyyaml / lz4."""
    joined = " ".join(base_deps).lower()
    for pkg in ("wgpu", "numpy", "pillow", "glfw", "pyyaml", "lz4"):
        assert pkg in joined, f"Missing core base dep: {pkg}"


def test_base_deps_count_is_small(base_deps: list[str]) -> None:
    """Base deps must remain <= 8 entries. Adding to base is a policy change."""
    assert len(base_deps) <= 8, (
        f"Base deps grew to {len(base_deps)} entries. New deps belong in an extra."
    )


# ---------------------------------------------------------------------------
# 6. Version pin philosophy — no `==` exact pins
# ---------------------------------------------------------------------------


def test_no_exact_pins_in_extras(extras: dict[str, list[str]]) -> None:
    """Extras must use ``>=`` minimums, never exact ``==`` pins.

    Rationale: engine soft-imports everything; users often already
    have a compatible version of the dep from another package.
    """
    for name, deps in extras.items():
        for dep in deps:
            # Self-references (``pharos-engine[...]``) are exempt.
            if dep.lower().startswith("pharos-engine"):
                continue
            assert "==" not in dep, (
                f"Exact pin in extra `{name}`: `{dep}` — use `>=` instead."
            )


def test_no_exact_pins_in_base(base_deps: list[str]) -> None:
    """Base deps must not exact-pin either."""
    for dep in base_deps:
        assert "==" not in dep, f"Exact pin in base deps: `{dep}`"
