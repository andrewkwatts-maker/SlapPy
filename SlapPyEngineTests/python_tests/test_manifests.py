"""Engine tests for AssetManifest, SceneManifest, LayerManifest, and related — headless."""
from __future__ import annotations
import pytest
import tempfile
from pathlib import Path


class TestLayerManifest:
    def test_init_stores_fields(self):
        from pharos_engine.asset_manifest import LayerManifest
        lm = LayerManifest(name="body", texture="sprites/car.png", opacity=0.9)
        assert lm.name == "body"
        assert lm.texture == "sprites/car.png"
        assert lm.opacity == pytest.approx(0.9)

    def test_default_values(self):
        from pharos_engine.asset_manifest import LayerManifest
        lm = LayerManifest(name="test")
        assert lm.width == 64
        assert lm.height == 64
        assert lm.opacity == pytest.approx(1.0)
        assert lm.deformable is False
        assert lm.lighting_mode == "2d"

    def test_to_dict(self):
        from pharos_engine.asset_manifest import LayerManifest
        lm = LayerManifest(name="shadow", texture="sprites/shadow.png", opacity=0.5)
        d = lm.to_dict()
        assert d["name"] == "shadow"
        assert d["texture"] == "sprites/shadow.png"
        assert d["opacity"] == pytest.approx(0.5)

    def test_from_dict_roundtrip(self):
        from pharos_engine.asset_manifest import LayerManifest
        lm = LayerManifest(name="body", texture="t.png", opacity=0.75, deformable=True)
        d = lm.to_dict()
        restored = LayerManifest.from_dict(d)
        assert restored.name == "body"
        assert restored.texture == "t.png"
        assert restored.opacity == pytest.approx(0.75)
        assert restored.deformable is True

    def test_from_dict_missing_optional(self):
        from pharos_engine.asset_manifest import LayerManifest
        lm = LayerManifest.from_dict({"name": "minimal"})
        assert lm.name == "minimal"
        assert lm.texture is None

    def test_tint_stored_as_tuple(self):
        from pharos_engine.asset_manifest import LayerManifest
        lm = LayerManifest(name="t", tint=(1.0, 0.5, 0.0, 1.0))
        d = lm.to_dict()
        restored = LayerManifest.from_dict(d)
        assert len(restored.tint) == 4


class TestCollisionManifest:
    def test_init_defaults(self):
        from pharos_engine.asset_manifest import CollisionManifest
        cm = CollisionManifest()
        assert cm.type == "aabb"
        assert cm.width == 32
        assert cm.height == 32

    def test_to_dict(self):
        from pharos_engine.asset_manifest import CollisionManifest
        cm = CollisionManifest(type="circle", width=48, height=48)
        d = cm.to_dict()
        assert d["type"] == "circle"
        assert d["width"] == 48

    def test_from_dict_roundtrip(self):
        from pharos_engine.asset_manifest import CollisionManifest
        cm = CollisionManifest(type="aabb", width=64, height=32)
        restored = CollisionManifest.from_dict(cm.to_dict())
        assert restored.type == "aabb"
        assert restored.width == 64
        assert restored.height == 32


class TestSubscriptionEntry:
    def test_init_stores_event(self):
        from pharos_engine.asset_manifest import SubscriptionEntry
        se = SubscriptionEntry(event="Vehicle.fuel_level")
        assert se.event == "Vehicle.fuel_level"
        assert se.handler is None

    def test_derived_handler(self):
        from pharos_engine.asset_manifest import SubscriptionEntry
        se = SubscriptionEntry(event="Asset.Car.Gas.Empty")
        assert se.derived_handler() == "on_event_asset_car_gas_empty"

    def test_to_dict_with_handler(self):
        from pharos_engine.asset_manifest import SubscriptionEntry
        se = SubscriptionEntry(event="Race.Lap", handler="on_lap")
        d = se.to_dict()
        assert d["event"] == "Race.Lap"
        assert d["handler"] == "on_lap"

    def test_to_dict_without_handler(self):
        from pharos_engine.asset_manifest import SubscriptionEntry
        se = SubscriptionEntry(event="Race.Lap")
        d = se.to_dict()
        assert "handler" not in d

    def test_from_dict_string(self):
        from pharos_engine.asset_manifest import SubscriptionEntry
        se = SubscriptionEntry.from_dict("Vehicle.speed")
        assert se.event == "Vehicle.speed"
        assert se.handler is None

    def test_from_dict_dict(self):
        from pharos_engine.asset_manifest import SubscriptionEntry
        se = SubscriptionEntry.from_dict({"event": "Race.Lap", "handler": "my_fn"})
        assert se.event == "Race.Lap"
        assert se.handler == "my_fn"


class TestAssetManifest:
    def _make_manifest(self):
        from pharos_engine.asset_manifest import AssetManifest, LayerManifest, CollisionManifest
        return AssetManifest(
            name="Car",
            layers=[LayerManifest(name="body", texture="sprites/car.png")],
            scripts=["scripts/car.py"],
            collision=CollisionManifest(width=48, height=32),
            properties={"speed": 100, "fuel": 1.0},
        )

    def test_to_dict_has_name(self):
        m = self._make_manifest()
        d = m.to_dict()
        assert d["name"] == "Car"

    def test_to_dict_has_layers(self):
        m = self._make_manifest()
        d = m.to_dict()
        assert len(d["layers"]) == 1
        assert d["layers"][0]["name"] == "body"

    def test_to_dict_has_collision(self):
        m = self._make_manifest()
        d = m.to_dict()
        assert "collision" in d
        assert d["collision"]["width"] == 48

    def test_from_dict_roundtrip(self):
        from pharos_engine.asset_manifest import AssetManifest
        m = self._make_manifest()
        restored = AssetManifest.from_dict(m.to_dict())
        assert restored.name == "Car"
        assert len(restored.layers) == 1
        assert restored.properties["speed"] == 100

    def test_from_dict_no_collision(self):
        from pharos_engine.asset_manifest import AssetManifest
        m = AssetManifest.from_dict({"name": "Empty", "layers": []})
        assert m.collision is None

    def test_from_dict_with_subscriptions(self):
        from pharos_engine.asset_manifest import AssetManifest
        d = {
            "name": "ReactiveEntity",
            "layers": [],
            "subscriptions": [
                {"event": "Vehicle.speed", "handler": "on_speed"},
                "Race.Lap",
            ],
        }
        m = AssetManifest.from_dict(d)
        assert len(m.subscriptions) == 2
        assert m.subscriptions[0].event == "Vehicle.speed"
        assert m.subscriptions[1].event == "Race.Lap"

    def test_checksum_deterministic(self):
        m = self._make_manifest()
        assert m.checksum() == m.checksum()

    def test_checksum_changes_on_modification(self):
        from pharos_engine.asset_manifest import AssetManifest
        m1 = AssetManifest(name="A")
        m2 = AssetManifest(name="B")
        assert m1.checksum() != m2.checksum()

    def test_checksum_is_hex_string(self):
        m = self._make_manifest()
        cs = m.checksum()
        assert isinstance(cs, str)
        assert len(cs) == 64  # SHA-256 hex

    def test_save_and_load_roundtrip(self):
        from pharos_engine.asset_manifest import AssetManifest
        m = self._make_manifest()
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "car.yml"
            m.save(str(path))
            restored = AssetManifest.load(str(path))
        assert restored.name == "Car"
        assert len(restored.layers) == 1
        assert restored.properties["speed"] == 100


class TestSceneManifest:
    def test_init(self):
        from pharos_engine.asset_manifest import SceneManifest
        sm = SceneManifest(name="Level1")
        assert sm.name == "Level1"
        assert sm.type == "scene"

    def test_to_dict(self):
        from pharos_engine.asset_manifest import SceneManifest
        sm = SceneManifest(
            name="Race",
            entities=[{"manifest": "assets/car.yml", "position": [0, 0]}],
            lighting={"ambient_intensity": 0.3},
        )
        d = sm.to_dict()
        assert d["name"] == "Race"
        assert len(d["entities"]) == 1
        assert d["lighting"]["ambient_intensity"] == pytest.approx(0.3)

    def test_from_dict_roundtrip(self):
        from pharos_engine.asset_manifest import SceneManifest
        sm = SceneManifest(
            name="Test",
            entities=[{"manifest": "x.yml"}],
            post_process=[{"type": "vignette", "strength": 0.4}],
        )
        restored = SceneManifest.from_dict(sm.to_dict())
        assert restored.name == "Test"
        assert len(restored.entities) == 1
        assert len(restored.post_process) == 1

    def test_from_dict_empty_scene(self):
        from pharos_engine.asset_manifest import SceneManifest
        sm = SceneManifest.from_dict({"name": "Empty"})
        assert sm.entities == []
        assert sm.lighting == {}
        assert sm.post_process == []
