"""Engine tests for MaterialMap, ShaderBinding, and content_encrypt — headless."""
from __future__ import annotations
import pytest


# ---------------------------------------------------------------------------
# MaterialMap / ColorRange
# ---------------------------------------------------------------------------

class TestColorRange:
    def test_matches_within_range(self):
        from pharos_engine.material.map import ColorRange
        cr = ColorRange(r=(100, 200), g=(50, 150), b=(0, 100))
        assert cr.matches(150, 100, 50) is True

    def test_matches_on_boundary(self):
        from pharos_engine.material.map import ColorRange
        cr = ColorRange(r=(0, 255), g=(0, 255), b=(0, 255))
        assert cr.matches(0, 0, 0) is True
        assert cr.matches(255, 255, 255) is True

    def test_not_matches_outside(self):
        from pharos_engine.material.map import ColorRange
        cr = ColorRange(r=(0, 100), g=(0, 100), b=(0, 100))
        assert cr.matches(200, 50, 50) is False
        assert cr.matches(50, 200, 50) is False
        assert cr.matches(50, 50, 200) is False

    def test_default_range_full(self):
        from pharos_engine.material.map import ColorRange
        cr = ColorRange()
        assert cr.matches(128, 64, 32) is True


class TestMaterialMap:
    def test_add_material(self):
        from pharos_engine.material.map import MaterialMap, ColorRange
        mm = MaterialMap()
        m = mm.add("grass", ColorRange(r=(0, 80), g=(100, 200), b=(0, 80)))
        assert m.name == "grass"

    def test_match_returns_correct_material(self):
        from pharos_engine.material.map import MaterialMap, ColorRange
        mm = MaterialMap()
        mm.add("grass", ColorRange(r=(0, 80), g=(100, 200), b=(0, 80)))
        mm.add("dirt", ColorRange(r=(100, 180), g=(60, 120), b=(0, 60)))
        result = mm.match(40, 150, 30)  # grass
        assert result is not None
        assert result.name == "grass"

    def test_match_returns_none_when_no_match(self):
        from pharos_engine.material.map import MaterialMap, ColorRange
        mm = MaterialMap()
        mm.add("grass", ColorRange(r=(0, 50), g=(0, 50), b=(0, 50)))
        assert mm.match(200, 200, 200) is None

    def test_first_match_wins(self):
        from pharos_engine.material.map import MaterialMap, ColorRange
        mm = MaterialMap()
        mm.add("first", ColorRange(r=(0, 255), g=(0, 255), b=(0, 255)))
        mm.add("second", ColorRange(r=(0, 255), g=(0, 255), b=(0, 255)))
        result = mm.match(128, 128, 128)
        assert result.name == "first"

    def test_material_behaviors_stored(self):
        from pharos_engine.material.map import MaterialMap, ColorRange
        mm = MaterialMap()
        m = mm.add("road", ColorRange(), behaviors=["solid", "slippery"])
        assert "solid" in m.behaviors
        assert "slippery" in m.behaviors

    def test_material_params_stored(self):
        from pharos_engine.material.map import MaterialMap, ColorRange
        mm = MaterialMap()
        m = mm.add("water", ColorRange(), params={"friction": 0.2, "depth": 0.5})
        assert m.params["friction"] == pytest.approx(0.2)

    def test_alpha_meaning_default(self):
        from pharos_engine.material.map import MaterialMap, ColorRange
        mm = MaterialMap()
        m = mm.add("test", ColorRange())
        assert m.alpha_meaning == "opacity"

    def test_empty_map_no_match(self):
        from pharos_engine.material.map import MaterialMap
        mm = MaterialMap()
        assert mm.match(0, 0, 0) is None

    def test_load_defaults_returns_material_map(self):
        from pharos_engine.material.map import MaterialMap
        mm = MaterialMap.load_defaults()
        assert isinstance(mm, MaterialMap)


# ---------------------------------------------------------------------------
# ShaderBinding
# ---------------------------------------------------------------------------

class TestShaderBindingEvaluate:
    def test_linear_midpoint(self):
        from pharos_engine.shader_binding import ShaderBinding
        sb = ShaderBinding(
            source_module="m", source_field="x",
            target_shader="s", target_param="p",
            transform="linear", input_range=(0.0, 1.0), output_range=(0.0, 10.0),
        )
        assert sb.evaluate(0.5) == pytest.approx(5.0)

    def test_linear_at_zero(self):
        from pharos_engine.shader_binding import ShaderBinding
        sb = ShaderBinding(
            source_module="m", source_field="x",
            target_shader="s", target_param="p",
            transform="linear", input_range=(0.0, 100.0), output_range=(0.0, 1.0),
        )
        assert sb.evaluate(0.0) == pytest.approx(0.0)

    def test_linear_at_max(self):
        from pharos_engine.shader_binding import ShaderBinding
        sb = ShaderBinding(
            source_module="m", source_field="x",
            target_shader="s", target_param="p",
            transform="linear", input_range=(0.0, 100.0), output_range=(0.0, 5.0),
        )
        assert sb.evaluate(100.0) == pytest.approx(5.0)

    def test_clamp_below_zero(self):
        from pharos_engine.shader_binding import ShaderBinding
        sb = ShaderBinding(
            source_module="m", source_field="x",
            target_shader="s", target_param="p",
            transform="linear", input_range=(0.0, 1.0), output_range=(0.0, 1.0),
            clamp=True,
        )
        assert sb.evaluate(-100.0) == pytest.approx(0.0)

    def test_clamp_above_max(self):
        from pharos_engine.shader_binding import ShaderBinding
        sb = ShaderBinding(
            source_module="m", source_field="x",
            target_shader="s", target_param="p",
            transform="linear", input_range=(0.0, 1.0), output_range=(0.0, 1.0),
            clamp=True,
        )
        assert sb.evaluate(999.0) == pytest.approx(1.0)

    def test_pow2_less_than_linear(self):
        from pharos_engine.shader_binding import ShaderBinding
        sb_lin = ShaderBinding(
            source_module="m", source_field="x",
            target_shader="s", target_param="p",
            transform="linear", input_range=(0.0, 1.0), output_range=(0.0, 1.0),
        )
        sb_pow2 = ShaderBinding(
            source_module="m", source_field="x",
            target_shader="s", target_param="p",
            transform="pow2", input_range=(0.0, 1.0), output_range=(0.0, 1.0),
        )
        assert sb_pow2.evaluate(0.5) < sb_lin.evaluate(0.5)

    def test_sqrt_greater_than_linear(self):
        from pharos_engine.shader_binding import ShaderBinding
        sb_lin = ShaderBinding(
            source_module="m", source_field="x",
            target_shader="s", target_param="p",
            transform="linear", input_range=(0.0, 1.0), output_range=(0.0, 1.0),
        )
        sb_sqrt = ShaderBinding(
            source_module="m", source_field="x",
            target_shader="s", target_param="p",
            transform="sqrt", input_range=(0.0, 1.0), output_range=(0.0, 1.0),
        )
        assert sb_sqrt.evaluate(0.25) > sb_lin.evaluate(0.25)

    def test_degenerate_range_no_crash(self):
        from pharos_engine.shader_binding import ShaderBinding
        sb = ShaderBinding(
            source_module="m", source_field="x",
            target_shader="s", target_param="p",
            transform="linear", input_range=(5.0, 5.0), output_range=(0.0, 1.0),
        )
        result = sb.evaluate(5.0)
        assert result == pytest.approx(0.0)


class TestShaderBindingWGSL:
    def test_to_wgsl_expr_returns_string(self):
        from pharos_engine.shader_binding import ShaderBinding
        sb = ShaderBinding(
            source_module="m", source_field="x",
            target_shader="s", target_param="p",
        )
        wgsl = sb.to_wgsl_expr()
        assert isinstance(wgsl, str)
        assert len(wgsl) > 0

    def test_to_wgsl_expr_contains_output_range(self):
        from pharos_engine.shader_binding import ShaderBinding
        sb = ShaderBinding(
            source_module="m", source_field="x",
            target_shader="s", target_param="p",
            output_range=(2.0, 8.0),
        )
        wgsl = sb.to_wgsl_expr()
        assert "2.0" in wgsl or "8.0" in wgsl

    def test_pow2_wgsl_contains_pow(self):
        from pharos_engine.shader_binding import ShaderBinding
        sb = ShaderBinding(
            source_module="m", source_field="x",
            target_shader="s", target_param="p",
            transform="pow2",
        )
        assert "pow" in sb.to_wgsl_expr()

    def test_sqrt_wgsl_contains_sqrt(self):
        from pharos_engine.shader_binding import ShaderBinding
        sb = ShaderBinding(
            source_module="m", source_field="x",
            target_shader="s", target_param="p",
            transform="sqrt",
        )
        assert "sqrt" in sb.to_wgsl_expr()


# ---------------------------------------------------------------------------
# content_encrypt
# ---------------------------------------------------------------------------

class TestDeriveKey:
    def test_returns_32_byte_key(self):
        from pharos_engine.content_encrypt import derive_key
        key, salt = derive_key("test-passphrase")
        assert len(key) == 32

    def test_returns_16_byte_salt(self):
        from pharos_engine.content_encrypt import derive_key
        key, salt = derive_key("test")
        assert len(salt) == 16

    def test_same_passphrase_same_salt_gives_same_key(self):
        from pharos_engine.content_encrypt import derive_key
        salt = b"\x00" * 16
        key1, _ = derive_key("passphrase", salt=salt)
        key2, _ = derive_key("passphrase", salt=salt)
        assert key1 == key2

    def test_different_passphrase_gives_different_key(self):
        from pharos_engine.content_encrypt import derive_key
        salt = b"\x01" * 16
        key1, _ = derive_key("password1", salt=salt)
        key2, _ = derive_key("password2", salt=salt)
        assert key1 != key2

    def test_different_salt_gives_different_key(self):
        from pharos_engine.content_encrypt import derive_key
        key1, _ = derive_key("same", salt=b"\x00" * 16)
        key2, _ = derive_key("same", salt=b"\xff" * 16)
        assert key1 != key2


class TestEncryptDecryptBytes:
    def test_roundtrip(self):
        from pharos_engine.content_encrypt import derive_key, encrypt_bytes, decrypt_bytes
        key, _ = derive_key("test-key", salt=b"\x42" * 16)
        data = b"hello, engine!"
        ct = encrypt_bytes(data, key)
        pt = decrypt_bytes(ct, key)
        assert pt == data

    def test_ciphertext_different_from_plaintext(self):
        from pharos_engine.content_encrypt import derive_key, encrypt_bytes
        key, _ = derive_key("test-key", salt=b"\x42" * 16)
        data = b"A" * 32
        ct = encrypt_bytes(data, key)
        assert ct != data

    def test_ciphertext_has_nonce_prepended(self):
        from pharos_engine.content_encrypt import derive_key, encrypt_bytes
        key, _ = derive_key("test-key", salt=b"\x42" * 16)
        data = b"short"
        ct = encrypt_bytes(data, key)
        # Nonce is 12 bytes, so ciphertext must be longer than data
        assert len(ct) > len(data)

    def test_two_encryptions_produce_different_ciphertext(self):
        from pharos_engine.content_encrypt import derive_key, encrypt_bytes
        key, _ = derive_key("test-key", salt=b"\x42" * 16)
        data = b"same data"
        ct1 = encrypt_bytes(data, key)
        ct2 = encrypt_bytes(data, key)
        # Different nonces → different ciphertexts
        assert ct1 != ct2

    def test_empty_data_roundtrip(self):
        from pharos_engine.content_encrypt import derive_key, encrypt_bytes, decrypt_bytes
        key, _ = derive_key("k", salt=b"\x01" * 16)
        ct = encrypt_bytes(b"", key)
        pt = decrypt_bytes(ct, key)
        assert pt == b""

    def test_large_data_roundtrip(self):
        from pharos_engine.content_encrypt import derive_key, encrypt_bytes, decrypt_bytes
        key, _ = derive_key("big-key", salt=b"\x10" * 16)
        data = b"\xAB\xCD" * 10000
        ct = encrypt_bytes(data, key)
        pt = decrypt_bytes(ct, key)
        assert pt == data


class TestEncryptDecryptFile:
    def test_roundtrip(self, tmp_path):
        from pharos_engine.content_encrypt import derive_key, encrypt_file, decrypt_file
        key, _ = derive_key("file-test", salt=b"\x55" * 16)
        src = tmp_path / "test.png"
        src.write_bytes(b"fake png data " * 20)
        dst = tmp_path / "test.png"
        encrypt_file(src, dst, key)
        enc_path = dst.with_suffix(".png.enc")
        if not enc_path.exists():
            enc_path = tmp_path / "test.png.enc"
        decrypted = decrypt_file(enc_path, key)
        assert decrypted == b"fake png data " * 20

    def test_enc_extension_added(self, tmp_path):
        from pharos_engine.content_encrypt import derive_key, encrypt_file
        key, _ = derive_key("ext-test", salt=b"\x33" * 16)
        src = tmp_path / "asset.bin"
        src.write_bytes(b"data")
        dst = tmp_path / "asset.bin"
        encrypt_file(src, dst, key)
        # The .enc extension should be added
        assert (tmp_path / "asset.bin.enc").exists()
