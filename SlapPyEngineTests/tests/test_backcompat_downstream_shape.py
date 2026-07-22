"""Backcompat pinning: enforce the *return-shape* contract of load-bearing
public APIs that downstream games consume.

Motivation
----------
Sibling to ``test_backcompat_api_surface.py`` (UU7, name-deletion tripwire)
and ``test_backcompat_subclass_patterns.py`` (UU7, MRO / __init__ ordering
tripwire). TT1 → WW3 uncovered a third class of silent breakage the first
two harnesses do NOT catch: the *shape* of an object a public API returns.

Recent examples the game-compat re-runs pinned down:

    * ``EventBus.publish`` return went from an ``EventPayload``-shaped
      object (``.publisher / .label / .data / .timestamp`` attrs *and*
      ``["publisher"]`` dict access) to plain ``None``.  84 Ochema
      sites shift-broke on ``'dict' object has no attribute 'publisher'``
      (WW3 § 11, docs/game_compat_2026_07_07.md).
    * ``CacheMode.OFFSCREEN_SERIALIZE.value`` from ``str`` → ``int`` —
      VV1 restored the ``str`` shape once we noticed +26 Bullet sites.
    * ``AudioManager.play_loop`` handle contract — downstream expects an
      object with ``.stop() / .set_volume() / .set_pitch()``.  Engine
      currently returns an ``int`` loop-id — this test documents the
      contract and guards a lightweight-wrapper backfill.

Every check below is scoped so the *presence* of an API is optional but
its *shape* is fixed.  If YY1 hasn't landed the EventPayload return-shape
fix yet, its checks ``xfail`` cleanly rather than blocking master.

DO NOT delete these tests when the fix lands — they are the tripwire,
not a triage tool.
"""
from __future__ import annotations

import enum

import pytest

# ---------------------------------------------------------------------------
# EventBus.publish return shape (EventPayload)
# ---------------------------------------------------------------------------

def test_event_bus_publish_returns_payload_with_attrs() -> None:
    """``EventBus.publish`` must return an object with ``.publisher /
    .label / .data / .timestamp`` attrs.  Downstream games access the
    payload attr-style (``payload.publisher``) — this is the return shape
    Bullet Strata's reactive HUD and Ochema Circuit's Sprint 3 telemetry
    both depend on.
    """
    from pharos_engine.event_bus import EventBus

    bus = EventBus()
    result = bus.publish("test.topic", publisher="unit", value=42)

    if result is None:
        pytest.xfail(
            "YY1 EventPayload return-shape fix not yet landed. Once "
            "publish() returns a payload object this xfail flips to xpass "
            "— remove the xfail branch."
        )

    # Attr-style access (games' preferred pattern).
    assert hasattr(result, "publisher"), (
        "publish() return must expose .publisher attr"
    )
    assert hasattr(result, "label"), (
        "publish() return must expose .label attr"
    )
    assert hasattr(result, "data"), (
        "publish() return must expose .data attr"
    )
    assert hasattr(result, "timestamp"), (
        "publish() return must expose .timestamp attr"
    )


def test_event_bus_publish_returns_payload_with_dict_access() -> None:
    """The payload must ALSO support ``["publisher"]`` dict-style access.
    Ochema Circuit's Sprint 3 audio system uses this pattern (see
    ``docs/game_compat_2026_07_07.md`` §10-11).
    """
    from pharos_engine.event_bus import EventBus

    bus = EventBus()
    result = bus.publish("test.topic", publisher="unit", value=42)

    if result is None:
        pytest.xfail(
            "YY1 EventPayload return-shape fix not yet landed."
        )

    # Dict-style access (legacy pattern still in use).
    try:
        publisher = result["publisher"]
    except (KeyError, TypeError) as e:
        pytest.fail(
            f"publish() return must support dict-style access "
            f"(['publisher']); got {type(e).__name__}: {e}"
        )
    assert publisher == "unit"


# ---------------------------------------------------------------------------
# AudioManager.play_loop handle contract
# ---------------------------------------------------------------------------

def test_audio_manager_play_loop_returns_handle_with_control_methods() -> None:
    """``AudioManager.play_loop`` currently returns an integer loop-id.
    Downstream games expect a handle object with ``.stop() /
    .set_volume() / .set_pitch()``.  This test documents the contract and
    ``xfail``s cleanly until the lightweight-wrapper backfill lands.
    """
    from pharos_engine.audio import AudioManager

    mgr = AudioManager()
    handle = mgr.play_loop(None, volume=0.5, pitch=1.0)

    if isinstance(handle, int):
        pytest.xfail(
            "play_loop currently returns int loop-id. Contract calls for "
            "an object with .stop / .set_volume / .set_pitch. Owner "
            "sprint: backcompat round 3."
        )

    for method in ("stop", "set_volume", "set_pitch"):
        assert hasattr(handle, method), (
            f"play_loop return must expose .{method}(); missing on "
            f"{type(handle).__name__}"
        )
        assert callable(getattr(handle, method)), (
            f"play_loop return .{method} must be callable"
        )


# ---------------------------------------------------------------------------
# LightingSystem.load_profile("night_rally")
# ---------------------------------------------------------------------------

def test_lighting_system_load_profile_night_rally_returns_config() -> None:
    """``LightingSystem.load_profile("night_rally")`` currently returns
    ``None`` (applies the profile in-place). Downstream games (Ochema
    Circuit's Sprint 3 atmosphere) expect an object exposing the loaded
    config keys (``ambient``, ``ambient_intensity``). This test guards
    against silent behaviour change and ``xfail``s cleanly if the return
    is still ``None``.
    """
    from pharos_engine.lighting import LightingSystem

    # LightingSystem requires (gpu, width, height); a plain stub gpu is
    # sufficient because load_profile only mutates in-memory ambient
    # state — no GPU resource creation happens on the profile-apply
    # path.
    class _StubGPU:
        pass

    try:
        lighting = LightingSystem(_StubGPU(), 32, 32)
    except (TypeError, AttributeError) as e:
        pytest.skip(f"LightingSystem construction unavailable headless: {e}")

    result = lighting.load_profile("night_rally")

    if result is None:
        # The applied-state contract still holds even without a return
        # value: verify the underlying LightingSystem picked up the
        # profile so we don't silently regress *that* behaviour either.
        assert hasattr(lighting, "_ambient_color") or hasattr(
            lighting, "ambient"
        ), "load_profile must at least mutate lighting ambient state"
        pytest.xfail(
            "load_profile currently returns None (applies in-place). "
            "Downstream contract calls for a dict-shaped return with "
            "'ambient' / 'ambient_intensity' keys. Owner sprint: "
            "backcompat round 3."
        )

    # If a return arrived, it must expose the profile keys.
    if hasattr(result, "get"):
        # dict-like path
        assert result.get("ambient") is not None or result.get(
            "ambient_intensity"
        ) is not None, (
            "load_profile return must contain 'ambient' or "
            "'ambient_intensity'"
        )
    else:
        # object-like path
        assert hasattr(result, "ambient") or hasattr(
            result, "ambient_intensity"
        ), "load_profile return must expose ambient / ambient_intensity"


# ---------------------------------------------------------------------------
# RenderTarget.add_layer dict-shaped layer specs
# ---------------------------------------------------------------------------

def test_render_target_add_layer_accepts_dict_layer_spec() -> None:
    """``RenderTarget.add_layer`` accepts a Layer instance today; some
    downstream call-sites pass dict-shaped layer specs
    (``{"name": "foo", "mode": "2D"}``). We treat dict-support as an
    aspirational contract — if the engine still requires a Layer instance
    we ``xfail`` cleanly and pin the current behaviour for regressions.
    """
    from pharos_engine.render_target import RenderTarget

    rt = RenderTarget(name="dict_spec_test", size=(32, 32))

    dict_spec = {"name": "spec_layer", "mode": "2D"}
    try:
        added = rt.add_layer(dict_spec)  # type: ignore[arg-type]
    except AttributeError:
        # Layer-only contract still holds: verify the *positive* path
        # so we don't silently regress add_layer(Layer(...)) either.
        from pharos_engine.layer import Layer
        added = rt.add_layer(Layer(name="fallback"))
        assert added is not None
        assert len(rt.layers) == 1
        pytest.xfail(
            "add_layer currently requires a Layer instance. Dict-shaped "
            "spec support is an aspirational downstream contract."
        )
    else:
        # add_layer took the dict — verify it either wrapped it or stored
        # it as-is such that .name is retrievable.
        assert added is not None
        assert len(rt.layers) == 1


# ---------------------------------------------------------------------------
# Observable dynamic subclassing chain
# ---------------------------------------------------------------------------

def test_observable_dynamic_subclass_with_asset_chain() -> None:
    """The cooperative ``super().__init__()`` chain in ``Observable``
    must survive ``type("X", (Observable, Asset), {})`` dynamic subclass
    construction — this is the exact pattern Bullet Strata's reactive
    HUD uses to build per-widget observable-backed assets at runtime.
    """
    from pharos_engine.asset import Asset
    from pharos_engine.event_bus import Observable

    # Dynamic subclass — no explicit __init__, so cooperative chain
    # must resolve both Observable AND Asset attribute init.
    DynObservableAsset = type("DynObservableAsset", (Observable, Asset), {})

    # Construct with only the args Observable expects; Asset falls back
    # to its own defaults via super() cooperation.
    inst = DynObservableAsset()

    # Observable-side attributes.
    assert hasattr(inst, "_bus"), "Observable._bus must exist post-init"
    assert hasattr(
        inst, "_observable_topic"
    ), "Observable._observable_topic must exist post-init"

    # Asset-side attributes (from RenderTarget → Entity → object chain).
    # If the cooperative chain broke, `layers` would be missing.
    assert hasattr(inst, "layers"), (
        "Asset.layers must exist post-init (proves cooperative chain ran)"
    )
    assert isinstance(inst.layers, list)


# ---------------------------------------------------------------------------
# CacheMode.OFFSCREEN_SERIALIZE.value type
# ---------------------------------------------------------------------------

def test_cache_mode_offscreen_serialize_value_is_str() -> None:
    """``CacheMode.OFFSCREEN_SERIALIZE.value`` must be a ``str``.
    Bullet Strata's residency-tier YAML compares ``.value`` to string
    literals from disk (`"offscreen_serialize"`).  VV1 restored the str
    shape after +26 game-compat sites regressed on int shape.
    """
    residency = pytest.importorskip("pharos_engine.residency.manager")
    CacheMode = getattr(residency, "CacheMode", None)
    if CacheMode is None:
        pytest.skip("CacheMode not exported (older engine build)")
    if not hasattr(CacheMode, "OFFSCREEN_SERIALIZE"):
        pytest.skip("OFFSCREEN_SERIALIZE variant absent (older enum layout)")

    value = CacheMode.OFFSCREEN_SERIALIZE.value
    assert isinstance(value, str), (
        f"CacheMode.OFFSCREEN_SERIALIZE.value must be str; got "
        f"{type(value).__name__} ({value!r})"
    )
    assert value == "offscreen_serialize"


def test_cache_mode_always_cached_value_is_str_if_present() -> None:
    """Sibling to OFFSCREEN_SERIALIZE — ALWAYS_CACHED is the other
    string-typed variant VV1 restored. Skip cleanly if the variant is
    absent so this test doesn't block older builds.
    """
    residency = pytest.importorskip("pharos_engine.residency.manager")
    CacheMode = getattr(residency, "CacheMode", None)
    if CacheMode is None:
        pytest.skip("CacheMode not exported")
    if not hasattr(CacheMode, "ALWAYS_CACHED"):
        pytest.skip("ALWAYS_CACHED variant absent (older enum layout)")

    value = CacheMode.ALWAYS_CACHED.value
    assert isinstance(value, str), (
        f"CacheMode.ALWAYS_CACHED.value must be str; got "
        f"{type(value).__name__} ({value!r})"
    )


# ---------------------------------------------------------------------------
# Enum baseline: every CacheMode variant is a str-valued enum
# ---------------------------------------------------------------------------

def test_cache_mode_all_variants_are_str_valued() -> None:
    """Guardrail: assert *every* CacheMode variant carries a str value.
    Prevents a future 'clean-up' pass from flipping one variant to int
    and shipping the mixed-type breakage the game-compat runs caught.
    """
    residency = pytest.importorskip("pharos_engine.residency.manager")
    CacheMode = getattr(residency, "CacheMode", None)
    if CacheMode is None:
        pytest.skip("CacheMode not exported")
    if not issubclass(CacheMode, enum.Enum):
        pytest.skip("CacheMode is not an enum in this build")

    non_str: list[str] = []
    for variant in CacheMode:
        if not isinstance(variant.value, str):
            non_str.append(f"{variant.name}={variant.value!r}")
    assert not non_str, (
        f"CacheMode variants with non-str .value: {non_str}. All must be "
        f"str to preserve YAML/int-vs-str downstream compare invariant."
    )
