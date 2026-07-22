"""Tests for pharos_engine.asset_import.mtl_resolver (JJ2 — Nova3D parity sprint 2)."""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from pharos_engine.asset_import import (
    ImportResult,
    MtlMaterialDef,
    import_obj,
    import_obj_with_materials,
    mtl_to_material,
    parse_mtl,
    resolve_mtl_references,
)
from pharos_engine.asset_import.mtl_resolver import _ns_to_roughness
from pharos_engine.asset_import.samples import (
    TRIANGLE_MTL,
    TRIANGLE_MTL_OBJ,
    TRIANGLE_OBJ,
)


# ---------------------------------------------------------------------------
# parse_mtl — golden path
# ---------------------------------------------------------------------------

def test_parse_mtl_sample_returns_one_material():
    defs = parse_mtl(TRIANGLE_MTL)
    assert len(defs) == 1
    assert "red_plain" in defs


def test_parse_mtl_sample_red_plain_values():
    defs = parse_mtl(TRIANGLE_MTL)
    m = defs["red_plain"]
    assert isinstance(m, MtlMaterialDef)
    assert m.name == "red_plain"
    assert m.kd == pytest.approx((0.8, 0.2, 0.2))
    assert m.ka == pytest.approx((0.1, 0.02, 0.02))
    assert m.ns == pytest.approx(32.0)
    assert m.d == pytest.approx(1.0)
    assert m.illum == 2


# ---------------------------------------------------------------------------
# parse_mtl — multi-material
# ---------------------------------------------------------------------------

def _write_mtl(tmp_path: Path, text: str, name: str = "test.mtl") -> Path:
    p = tmp_path / name
    p.write_text(textwrap.dedent(text), encoding="utf-8")
    return p


def test_parse_mtl_three_materials(tmp_path):
    mtl = _write_mtl(
        tmp_path,
        """
        newmtl a
        Kd 1 0 0
        newmtl b
        Kd 0 1 0
        newmtl c
        Kd 0 0 1
        """,
    )
    defs = parse_mtl(mtl)
    assert set(defs.keys()) == {"a", "b", "c"}
    assert defs["a"].kd == pytest.approx((1.0, 0.0, 0.0))
    assert defs["b"].kd == pytest.approx((0.0, 1.0, 0.0))
    assert defs["c"].kd == pytest.approx((0.0, 0.0, 1.0))


def test_parse_mtl_empty_file(tmp_path):
    mtl = _write_mtl(tmp_path, "")
    assert parse_mtl(mtl) == {}


def test_parse_mtl_only_comments(tmp_path):
    mtl = _write_mtl(tmp_path, "# just a comment\n# another\n")
    assert parse_mtl(mtl) == {}


def test_parse_mtl_missing_file_returns_empty(tmp_path):
    with pytest.warns(UserWarning):
        result = parse_mtl(tmp_path / "does_not_exist.mtl")
    assert result == {}


def test_parse_mtl_corrupt_line_produces_partial(tmp_path):
    mtl = _write_mtl(
        tmp_path,
        """
        newmtl good
        Kd 0.5 0.5 0.5
        Ns not_a_number
        newmtl also_good
        Kd 0.1 0.2 0.3
        """,
    )
    with pytest.warns(UserWarning):
        defs = parse_mtl(mtl)
    assert "good" in defs
    assert "also_good" in defs
    assert defs["also_good"].kd == pytest.approx((0.1, 0.2, 0.3))


# ---------------------------------------------------------------------------
# parse_mtl — texture paths
# ---------------------------------------------------------------------------

def test_parse_mtl_texture_paths_resolved(tmp_path):
    mtl = _write_mtl(
        tmp_path,
        """
        newmtl textured
        Kd 1 1 1
        map_Kd diffuse.png
        map_Bump normal.png
        map_Ks specular.png
        map_Ns rough.png
        map_d opacity.png
        """,
    )
    defs = parse_mtl(mtl)
    m = defs["textured"]
    assert m.map_kd is not None and m.map_kd.name == "diffuse.png"
    assert m.map_bump is not None and m.map_bump.name == "normal.png"
    assert m.map_ks is not None and m.map_ks.name == "specular.png"
    assert m.map_ns is not None and m.map_ns.name == "rough.png"
    assert m.map_d is not None and m.map_d.name == "opacity.png"


def test_parse_mtl_texture_options_skipped(tmp_path):
    mtl = _write_mtl(
        tmp_path,
        """
        newmtl opts
        map_Kd -clamp on -o 0.1 0.2 0.3 -s 1 1 1 albedo.png
        """,
    )
    defs = parse_mtl(mtl)
    assert defs["opts"].map_kd is not None
    assert defs["opts"].map_kd.name == "albedo.png"


def test_parse_mtl_tr_and_d_kept_consistent(tmp_path):
    mtl = _write_mtl(
        tmp_path,
        """
        newmtl half
        Kd 1 1 1
        d 0.5
        """,
    )
    defs = parse_mtl(mtl)
    assert defs["half"].d == pytest.approx(0.5)
    assert defs["half"].tr == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# ns → roughness heuristic
# ---------------------------------------------------------------------------

def test_ns_to_roughness_zero_is_matte():
    assert _ns_to_roughness(0.0) == pytest.approx(1.0)


def test_ns_to_roughness_900_is_smooth():
    assert _ns_to_roughness(900.0) == pytest.approx(0.05)


def test_ns_to_roughness_above_900_clipped():
    assert _ns_to_roughness(5000.0) == pytest.approx(0.05)


def test_ns_to_roughness_negative_treated_as_matte():
    assert _ns_to_roughness(-10.0) == pytest.approx(1.0)


def test_ns_to_roughness_450_is_midway():
    r = _ns_to_roughness(450.0)
    assert 0.4 < r < 0.6


# ---------------------------------------------------------------------------
# mtl_to_material — conversion
# ---------------------------------------------------------------------------

def test_mtl_to_material_base_color_rgba():
    mdef = MtlMaterialDef(name="x", kd=(0.8, 0.2, 0.2))
    mat = mtl_to_material(mdef)
    assert mat.base_color == pytest.approx((0.8, 0.2, 0.2, 1.0))


def test_mtl_to_material_alpha_from_tr():
    mdef = MtlMaterialDef(name="x", kd=(1.0, 1.0, 1.0), tr=0.5)
    mat = mtl_to_material(mdef)
    assert mat.base_color[3] == pytest.approx(0.5)
    assert mat.alpha_mode == "blend"


def test_mtl_to_material_alpha_from_d():
    mdef = MtlMaterialDef(name="x", kd=(1.0, 1.0, 1.0), d=0.3, tr=0.7)
    mat = mtl_to_material(mdef)
    assert mat.base_color[3] == pytest.approx(0.3)
    assert mat.alpha_mode == "blend"


def test_mtl_to_material_opaque_default():
    mdef = MtlMaterialDef(name="x", kd=(0.5, 0.5, 0.5))
    mat = mtl_to_material(mdef)
    assert mat.alpha_mode == "opaque"
    assert mat.base_color[3] == pytest.approx(1.0)


def test_mtl_to_material_metallic_defaults_zero():
    mdef = MtlMaterialDef(name="x", kd=(0.5, 0.5, 0.5))
    mat = mtl_to_material(mdef)
    assert mat.metallic == 0.0


def test_mtl_to_material_ns900_roughness_0_05():
    mdef = MtlMaterialDef(name="x", kd=(1, 1, 1), ns=900.0)
    mat = mtl_to_material(mdef)
    assert mat.roughness == pytest.approx(0.05)


def test_mtl_to_material_ns0_roughness_1():
    mdef = MtlMaterialDef(name="x", kd=(1, 1, 1), ns=0.0)
    mat = mtl_to_material(mdef)
    assert mat.roughness == pytest.approx(1.0)


def test_mtl_to_material_emissive_from_ka():
    mdef = MtlMaterialDef(name="x", kd=(1, 1, 1), ka=(0.4, 0.1, 0.1))
    mat = mtl_to_material(mdef)
    assert mat.emissive == pytest.approx((0.4, 0.1, 0.1))


def test_mtl_to_material_emissive_prefers_ke_when_present():
    mdef = MtlMaterialDef(name="x", kd=(1, 1, 1), ka=(0.4, 0.1, 0.1), ke=(0.9, 0.9, 0.0))
    mat = mtl_to_material(mdef)
    assert mat.emissive == pytest.approx((0.9, 0.9, 0.0))


def test_mtl_to_material_clips_kd_out_of_range():
    mdef = MtlMaterialDef(name="x", kd=(2.5, -0.5, 0.5))
    mat = mtl_to_material(mdef)
    assert 0.0 <= mat.base_color[0] <= 1.0
    assert 0.0 <= mat.base_color[1] <= 1.0
    assert mat.base_color[0] == pytest.approx(1.0)
    assert mat.base_color[1] == pytest.approx(0.0)


def test_mtl_to_material_texture_handle_defers(tmp_path):
    mdef = MtlMaterialDef(name="x", kd=(1, 1, 1), map_kd=Path("albedo.png"))
    mat = mtl_to_material(mdef)
    assert mat.base_color_texture is not None
    # Deferred — no width/height, no gpu_texture.
    assert getattr(mat.base_color_texture, "width", 0) == 0
    assert getattr(mat.base_color_texture, "gpu_texture", "sentinel") is None


def test_mtl_to_material_normal_map_wired():
    mdef = MtlMaterialDef(name="x", kd=(1, 1, 1), map_bump=Path("n.png"))
    mat = mtl_to_material(mdef)
    assert mat.normal_texture is not None


def test_mtl_to_material_no_textures():
    mdef = MtlMaterialDef(name="x", kd=(1, 1, 1))
    mat = mtl_to_material(mdef)
    assert mat.base_color_texture is None
    assert mat.normal_texture is None


# ---------------------------------------------------------------------------
# resolve_mtl_references — round-trip
# ---------------------------------------------------------------------------

def test_resolve_mtl_references_round_trip():
    result = import_obj(TRIANGLE_MTL_OBJ)
    materials = resolve_mtl_references(result, TRIANGLE_MTL_OBJ)
    assert "red_plain" in materials
    m = materials["red_plain"]
    assert m.name == "red_plain"
    assert m.base_color[:3] == pytest.approx((0.8, 0.2, 0.2))


def test_resolve_mtl_references_no_mtllib_returns_empty():
    result = import_obj(TRIANGLE_OBJ)
    materials = resolve_mtl_references(result, TRIANGLE_OBJ)
    assert materials == {}


def test_resolve_mtl_references_missing_mtl_warns(tmp_path):
    obj = tmp_path / "orphan.obj"
    obj.write_text(
        "mtllib missing.mtl\n"
        "v 0 0 0\nv 1 0 0\nv 0 1 0\n"
        "usemtl foo\n"
        "f 1 2 3\n",
        encoding="utf-8",
    )
    result = import_obj(obj)
    with pytest.warns(UserWarning):
        materials = resolve_mtl_references(result, obj)
    assert materials == {}


# ---------------------------------------------------------------------------
# import_obj_with_materials — end-to-end
# ---------------------------------------------------------------------------

def test_import_obj_with_materials_end_to_end():
    result = import_obj_with_materials(TRIANGLE_MTL_OBJ)
    assert isinstance(result, ImportResult)
    assert result.kind == "mesh"
    assert result.metadata["resolved_material_count"] == 1
    assert len(result.materials) == 1
    mat = result.materials[0]
    assert mat.name == "red_plain"
    assert mat.base_color[:3] == pytest.approx((0.8, 0.2, 0.2))


def test_import_obj_with_materials_no_mtl_preserves_original():
    result = import_obj_with_materials(TRIANGLE_OBJ)
    # triangle.obj has no mtllib; resolved count is 0 and no crash.
    assert result.metadata["resolved_material_count"] == 0


def test_import_obj_with_materials_metadata_has_by_name_map():
    result = import_obj_with_materials(TRIANGLE_MTL_OBJ)
    by_name = result.metadata.get("materials_by_name")
    assert by_name is not None
    assert "red_plain" in by_name


# ---------------------------------------------------------------------------
# Missing texture path handled gracefully
# ---------------------------------------------------------------------------

def test_missing_texture_path_still_produces_handle(tmp_path):
    mtl = _write_mtl(
        tmp_path,
        """
        newmtl m
        Kd 1 1 1
        map_Kd i_do_not_exist.png
        """,
    )
    defs = parse_mtl(mtl)
    # We don't actually load the file at parse time — the handle
    # just carries the path, deferred to a later load pass.
    mat = mtl_to_material(defs["m"])
    assert mat.base_color_texture is not None
    src = getattr(mat.base_color_texture, "source_path", None)
    assert src is not None
    assert Path(src).name == "i_do_not_exist.png"


# ---------------------------------------------------------------------------
# Dispatcher hook — .mtl routing
# ---------------------------------------------------------------------------

def test_dispatcher_classifies_mtl():
    from pharos_engine.asset_import import AssetImportDispatcher

    d = AssetImportDispatcher()
    assert d.classify("foo.mtl") == "material"


def test_dispatcher_imports_mtl():
    from pharos_engine.asset_import import AssetImportDispatcher

    d = AssetImportDispatcher()
    result = d.import_asset(TRIANGLE_MTL)
    assert result.kind == "material_library"
    assert result.metadata["material_count"] == 1
    assert "red_plain" in result.metadata["materials_by_name"]
