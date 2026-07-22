"""Sprint-3 lighting integration — preset chain regression tests.

Each preset composes only existing chain helpers (round-3 through round-9
polish), so these tests are CPU-only and run without a GPU.

The five required tests:

1. ``test_cinematic_has_dof_and_bloom``
2. ``test_arcade_has_no_dof``
3. ``test_iso_strategy_has_topo_dependencies_set``
4. ``test_each_preset_builds_without_error``
5. ``test_each_preset_can_serialize_to_dict_of_pass_names``
"""
from __future__ import annotations

import pytest

from pharos_engine.post_process import (
    PostProcessChain,
    arcade_chain,
    cinematic_chain,
    iso_strategy_chain,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _labels(chain: PostProcessChain) -> list[str]:
    return [p.label for p in chain.passes]


def _serialize(chain: PostProcessChain) -> dict[str, str]:
    """Each preset's passes serialised to {label: shader_path}.

    Used by the round-trip test; keeps the contract minimal so future polish
    rounds that add fields to ``PostProcessPass`` don't break the test.
    """
    return {p.label: p.shader_path for p in chain.passes}


# ---------------------------------------------------------------------------
# 1) Cinematic preset advertises both DoF and bloom
# ---------------------------------------------------------------------------


def test_cinematic_has_dof_and_bloom():
    """The cinematic preset must include both the round-9 DoF pass and the
    round-3 bloom pass — they're the two flagship knobs that distinguish it
    from the arcade preset."""
    chain = cinematic_chain()
    labels = _labels(chain)
    assert "dof" in labels, f"cinematic preset missing dof; got {labels}"
    assert "bloom" in labels, f"cinematic preset missing bloom; got {labels}"


# ---------------------------------------------------------------------------
# 2) Arcade preset never touches DoF (gameplay readability)
# ---------------------------------------------------------------------------


def test_arcade_has_no_dof():
    """The arcade preset must NOT include DoF — blurring the play-field is
    sub-optimal for top-down twitch gameplay (Ochema, Bullet Strata)."""
    chain = arcade_chain()
    labels = _labels(chain)
    assert "dof" not in labels, (
        f"arcade preset must not include DoF; got {labels}"
    )
    # Sanity: arcade still has bloom and outline so the punchy look survives.
    assert "bloom" in labels
    assert "outline" in labels


# ---------------------------------------------------------------------------
# 3) Iso-strategy preset wires up round-8-style topo dependencies
# ---------------------------------------------------------------------------


def test_iso_strategy_has_topo_dependencies_set():
    """At least one pass in the iso-strategy chain must declare a non-empty
    ``depends_on`` list — that's what proves the round-8 topo-sort hookup
    survived sprint-3 composition.

    Round-8 polish introduced the ``depends_on`` field on
    :class:`~pharos_engine.render_channel.RenderPass`; sprint-3 mirrors that
    contract onto :class:`~pharos_engine.post_process.chain.PostProcessPass`
    so post-process executors with topological scheduling can honour
    explicit dependency declarations.
    """
    chain = iso_strategy_chain()
    passes = chain.passes
    with_deps = [p for p in passes if p.depends_on]
    assert with_deps, (
        "iso_strategy_chain must declare at least one depends_on; "
        f"got labels={[p.label for p in passes]}"
    )

    # Stronger contract: every dependency name must reference a real pass
    # in the same chain — otherwise the executor would have nothing to wait
    # for and the declaration is a typo.
    all_labels = {p.label for p in passes}
    for p in with_deps:
        for dep in p.depends_on:
            assert dep in all_labels, (
                f"pass {p.label!r} depends on unknown pass {dep!r}; "
                f"known labels: {sorted(all_labels)}"
            )


# ---------------------------------------------------------------------------
# 4) Every preset builds without raising
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "factory",
    [cinematic_chain, arcade_chain, iso_strategy_chain],
    ids=["cinematic", "arcade", "iso_strategy"],
)
def test_each_preset_builds_without_error(factory):
    """No preset may raise during construction — CPU-only, no GPU required."""
    chain = factory()
    assert isinstance(chain, PostProcessChain)
    # And the chain must contain at least one enabled pass; an empty preset
    # would silently no-op for callers.
    assert chain.passes, f"{factory.__name__} produced an empty chain"


# ---------------------------------------------------------------------------
# 5) Each preset serialises to a dict of {label: shader_path}
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "factory",
    [cinematic_chain, arcade_chain, iso_strategy_chain],
    ids=["cinematic", "arcade", "iso_strategy"],
)
def test_each_preset_can_serialize_to_dict_of_pass_names(factory):
    """Each preset's chain serialises to a {label: shader_path} dict.

    This is the minimal save-game / asset-pipeline contract: dump the chain
    to YAML, load it back, get the same shader list.  We assert string keys
    and string values so the dict is YAML-safe out of the box.
    """
    chain = factory()
    payload = _serialize(chain)
    assert isinstance(payload, dict)
    assert payload, f"{factory.__name__} serialised to an empty dict"
    for k, v in payload.items():
        assert isinstance(k, str) and k, (
            f"{factory.__name__} produced a non-string / empty label: {k!r}"
        )
        assert isinstance(v, str) and v.endswith(".wgsl"), (
            f"{factory.__name__}[{k!r}] shader_path must end .wgsl; got {v!r}"
        )
    # Round-trip sanity: the number of distinct labels in the payload must
    # match the number of enabled passes (no silent label collisions).
    assert len(payload) == len(chain.passes), (
        f"{factory.__name__} has duplicate labels: {[p.label for p in chain.passes]}"
    )
