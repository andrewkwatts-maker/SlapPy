"""Coverage for the F6 per-subpackage structural Protocols.

The Round 3 Protocols (``WorldLike`` / ``Renderable`` / ``PostProcessParams``)
formalised cross-cutting duck types; the F6 batch extends Protocol coverage
to every subpackage that has plug-in extensibility:

* ``slappyengine.zones.ZoneProtocol``
* ``slappyengine.thermal.HeatSourceProtocol``
* ``slappyengine.material.NodeProtocol``
* ``slappyengine.post_process.PostProcessPassProtocol``
* ``slappyengine.telemetry.EventEmitterProtocol``
* ``slappyengine.telemetry.EventSubscriberProtocol``
* ``slappyengine.compute.ComputeKernelProtocol``
* ``slappyengine.ai.LLMBackendProtocol``

Each Protocol is ``@runtime_checkable``. Tests exercise:

* the canonical shipped implementation matches the Protocol;
* a lookalike that exposes the required surface is accepted;
* a bare object lacking the surface is rejected;
* the Protocol is exported from its subpackage's ``__all__``.
"""
from __future__ import annotations

import numpy as np
import pytest

# ---------------------------------------------------------------------------
# zones.ZoneProtocol
# ---------------------------------------------------------------------------


def test_zone_protocol_rectzone_matches() -> None:
    from slappyengine.zones import RectZone, ZoneProtocol

    z = RectZone(name="pad", x=0.0, y=0.0, w=10.0, h=10.0)
    assert isinstance(z, ZoneProtocol)


def test_zone_protocol_threshold_zone_matches() -> None:
    from slappyengine.zones import ThresholdZone, ZoneProtocol

    z = ThresholdZone(
        name="windshield", x=0.0, y=0.0, w=10.0, h=4.0, threshold=0.3,
    )
    assert isinstance(z, ZoneProtocol)


def test_zone_protocol_lookalike_matches() -> None:
    from slappyengine.zones import ZoneProtocol

    class RadialZone:
        def __init__(self) -> None:
            self.name = "radial"
            self.cx, self.cy, self.r = 0.0, 0.0, 5.0

        def contains_point(self, px: float, py: float) -> bool:
            return (px - self.cx) ** 2 + (py - self.cy) ** 2 <= self.r ** 2

    assert isinstance(RadialZone(), ZoneProtocol)


def test_zone_protocol_bare_object_rejected() -> None:
    from slappyengine.zones import ZoneProtocol

    class Bare:
        pass

    assert not isinstance(Bare(), ZoneProtocol)


def test_zone_protocol_exported() -> None:
    from slappyengine import zones

    assert "ZoneProtocol" in zones.__all__


# ---------------------------------------------------------------------------
# thermal.HeatSourceProtocol
# ---------------------------------------------------------------------------


def test_heat_source_protocol_lookalike_matches() -> None:
    from slappyengine.thermal import HeatField, HeatSourceProtocol

    class Brazier:
        temperature: float = 800.0

        def apply(self, field: HeatField, dt: float) -> None:
            field.temperature[0, 0] += self.temperature * dt

    assert isinstance(Brazier(), HeatSourceProtocol)


def test_heat_source_protocol_bare_object_rejected() -> None:
    from slappyengine.thermal import HeatSourceProtocol

    class Bare:
        temperature: float = 1.0
        # missing apply()

    assert not isinstance(Bare(), HeatSourceProtocol)


def test_heat_source_protocol_apply_actually_writes() -> None:
    """Round-trip: a conforming source writes into a real HeatField."""
    from slappyengine.thermal import HeatField, HeatSourceProtocol

    grid = np.zeros((4, 4), dtype=np.float64)
    field = HeatField(grid)

    class PointSource:
        temperature: float = 100.0

        def apply(self, field: HeatField, dt: float) -> None:
            field.temperature[2, 2] += self.temperature * dt

    src = PointSource()
    assert isinstance(src, HeatSourceProtocol)
    src.apply(field, 0.1)
    assert field.temperature[2, 2] == pytest.approx(10.0)


def test_heat_source_protocol_exported() -> None:
    from slappyengine import thermal

    assert "HeatSourceProtocol" in thermal.__all__


# ---------------------------------------------------------------------------
# material.NodeProtocol
# ---------------------------------------------------------------------------


def test_node_protocol_nodedef_matches() -> None:
    from slappyengine.material import NodeDef, NodeProtocol, UVNode

    n = UVNode()
    assert isinstance(n, NodeDef)
    assert isinstance(n, NodeProtocol)


def test_node_protocol_lookalike_matches() -> None:
    from slappyengine.material import NodeProtocol

    class CustomNode:
        node_type: str = "MyCustom"
        params: dict = {"strength": 1.0}

    assert isinstance(CustomNode(), NodeProtocol)


def test_node_protocol_bare_object_rejected() -> None:
    from slappyengine.material import NodeProtocol

    class Bare:
        # No node_type or params at all.
        pass

    assert not isinstance(Bare(), NodeProtocol)


def test_node_protocol_exported() -> None:
    from slappyengine import material

    assert "NodeProtocol" in material.__all__


# ---------------------------------------------------------------------------
# post_process.PostProcessPassProtocol
# ---------------------------------------------------------------------------


def test_post_process_pass_protocol_canonical_matches() -> None:
    from slappyengine.post_process import (
        PostProcessPass,
        PostProcessPassProtocol,
    )

    p = PostProcessPass(shader_path="bloom.wgsl", label="bloom")
    assert isinstance(p, PostProcessPassProtocol)


def test_post_process_pass_protocol_lookalike_matches() -> None:
    from slappyengine.post_process import PostProcessPassProtocol

    class ThirdPartyPass:
        shader_path: str = "neon.wgsl"
        label: str = "neon"
        enabled: bool = True

    assert isinstance(ThirdPartyPass(), PostProcessPassProtocol)


def test_post_process_pass_protocol_bare_object_rejected() -> None:
    from slappyengine.post_process import PostProcessPassProtocol

    class Bare:
        shader_path: str = "x.wgsl"
        # missing label, enabled

    assert not isinstance(Bare(), PostProcessPassProtocol)


def test_post_process_pass_protocol_exported() -> None:
    from slappyengine import post_process

    assert "PostProcessPassProtocol" in post_process.__all__


# ---------------------------------------------------------------------------
# telemetry.EventEmitterProtocol / EventSubscriberProtocol
# ---------------------------------------------------------------------------


def test_event_emitter_protocol_lookalike_matches() -> None:
    from slappyengine.telemetry import EventEmitterProtocol

    class PerSystemEmitter:
        def __init__(self, source: str) -> None:
            self.source = source

        def emit(self, name: str, **payload: object) -> None:
            payload["source"] = self.source

    e = PerSystemEmitter(source="physics")
    assert isinstance(e, EventEmitterProtocol)


def test_event_emitter_protocol_bare_object_rejected() -> None:
    from slappyengine.telemetry import EventEmitterProtocol

    class Bare:
        pass

    assert not isinstance(Bare(), EventEmitterProtocol)


def test_event_subscriber_protocol_callable_matches() -> None:
    from slappyengine.telemetry import EventSubscriberProtocol, TelemetryEvent

    class Handler:
        def __init__(self) -> None:
            self.received: list[TelemetryEvent] = []

        def __call__(self, event: TelemetryEvent) -> None:
            self.received.append(event)

    h = Handler()
    assert isinstance(h, EventSubscriberProtocol)


def test_event_subscriber_protocol_plain_function_matches() -> None:
    """Plain functions are also valid subscribers (they have __call__)."""
    from slappyengine.telemetry import EventSubscriberProtocol, TelemetryEvent

    def handle(event: TelemetryEvent) -> None:
        pass

    assert isinstance(handle, EventSubscriberProtocol)


def test_telemetry_protocols_exported() -> None:
    from slappyengine import telemetry

    assert "EventEmitterProtocol" in telemetry.__all__
    assert "EventSubscriberProtocol" in telemetry.__all__


# ---------------------------------------------------------------------------
# compute.ComputeKernelProtocol
# ---------------------------------------------------------------------------


def test_compute_kernel_protocol_canonical_matches() -> None:
    from slappyengine.compute import ComputeKernelProtocol, ComputePass

    p = ComputePass(
        source="@compute @workgroup_size(1) fn main() {}",
        entry_point="main",
        label="noop",
    )
    assert isinstance(p, ComputeKernelProtocol)


def test_compute_kernel_protocol_lookalike_matches() -> None:
    from slappyengine.compute import ComputeKernelProtocol

    class GeneratedKernel:
        source: str = "@compute @workgroup_size(64) fn main() {}"
        entry_point: str = "main"
        label: str = "generated"

    assert isinstance(GeneratedKernel(), ComputeKernelProtocol)


def test_compute_kernel_protocol_bare_object_rejected() -> None:
    from slappyengine.compute import ComputeKernelProtocol

    class Bare:
        source: str = "x"
        # missing entry_point + label

    assert not isinstance(Bare(), ComputeKernelProtocol)


def test_compute_kernel_protocol_exported() -> None:
    from slappyengine import compute

    assert "ComputeKernelProtocol" in compute.__all__


# ---------------------------------------------------------------------------
# ai.LLMBackendProtocol
# ---------------------------------------------------------------------------


def test_llm_backend_protocol_lookalike_matches() -> None:
    from slappyengine.ai import LLMBackendProtocol

    class StubBackend:
        def generate(
            self,
            prompt: str,
            system_prompt: str = "",
            temperature: float = 0.2,
        ) -> str:
            return f"stub-{prompt[:8]}"

        def is_available(self) -> bool:
            return True

        def list_models(self) -> list[str]:
            return ["stub-1.0"]

    b = StubBackend()
    assert isinstance(b, LLMBackendProtocol)
    assert b.generate("hello world") == "stub-hello wo"
    assert b.is_available() is True
    assert b.list_models() == ["stub-1.0"]


def test_llm_backend_protocol_missing_method_rejected() -> None:
    from slappyengine.ai import LLMBackendProtocol

    class PartialBackend:
        def generate(self, prompt: str, system_prompt: str = "",
                     temperature: float = 0.2) -> str:
            return ""
        # missing is_available + list_models

    assert not isinstance(PartialBackend(), LLMBackendProtocol)


def test_llm_backend_protocol_bare_object_rejected() -> None:
    from slappyengine.ai import LLMBackendProtocol

    class Bare:
        pass

    assert not isinstance(Bare(), LLMBackendProtocol)


def test_llm_backend_protocol_exported() -> None:
    from slappyengine import ai

    assert "LLMBackendProtocol" in ai.__all__


# ---------------------------------------------------------------------------
# Lifecycle contract documentation
# ---------------------------------------------------------------------------


def test_lifecycle_contract_doc_exists() -> None:
    """``docs/lifecycle_contract.md`` is the single-source-of-truth doc."""
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[2]
    doc = repo_root / "docs" / "lifecycle_contract.md"
    assert doc.exists(), f"lifecycle contract doc missing at {doc}"
    text = doc.read_text(encoding="utf-8")
    # Quick sanity checks: the three phases + at least one Protocol name.
    for phrase in ("start", "step", "shutdown", "on_tick", "Script"):
        assert phrase in text, f"lifecycle doc missing {phrase!r}"


def test_lifecycle_contract_doc_references_protocols() -> None:
    """The doc references the F6 Protocols so plug-in authors can find them."""
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[2]
    doc = repo_root / "docs" / "lifecycle_contract.md"
    text = doc.read_text(encoding="utf-8")
    for proto in (
        "ZoneProtocol",
        "HeatSourceProtocol",
        "NodeProtocol",
        "PostProcessPassProtocol",
        "EventEmitterProtocol",
        "EventSubscriberProtocol",
        "ComputeKernelProtocol",
        "LLMBackendProtocol",
    ):
        assert proto in text, f"lifecycle doc missing reference to {proto}"
