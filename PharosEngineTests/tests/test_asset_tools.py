"""Tests for AssetTools (sprite_tools, texture_tools, audio_tools)."""
import os
import pytest
import numpy as np
from PIL import Image


# ---------------------------------------------------------------------------
# sprite_tools
# ---------------------------------------------------------------------------

def test_generate_rotation_strip(tmp_path):
    from pharos_engine.tools.sprite_tools import generate_rotation_strip

    src = tmp_path / "src.png"
    img = Image.new("RGBA", (32, 32), (255, 0, 0, 255))
    img.save(str(src))
    out = tmp_path / "strip.png"
    generate_rotation_strip(str(src), str(out), frames=8, size=(32, 32))
    result = Image.open(str(out))
    assert result.width == 256 and result.height == 32  # 8 frames × 32 px


def test_generate_rotation_strip_16(tmp_path):
    from pharos_engine.tools.sprite_tools import generate_rotation_strip

    src = tmp_path / "src.png"
    img = Image.new("RGBA", (64, 64), (0, 255, 0, 255))
    img.save(str(src))
    out = tmp_path / "strip16.png"
    generate_rotation_strip(str(src), str(out), frames=16, size=(32, 32))
    result = Image.open(str(out))
    assert result.width == 512 and result.height == 32


def test_generate_noise_texture():
    from pharos_engine.tools.texture_tools import generate_noise_texture

    img = generate_noise_texture(mode="fbm", width=64, height=64, octaves=3)
    assert img.size == (64, 64)
    assert img.mode == "L"


def test_generate_noise_texture_worley():
    from pharos_engine.tools.texture_tools import generate_noise_texture

    img = generate_noise_texture(mode="worley", width=32, height=32)
    assert img.size == (32, 32)
    # Worley noise should have some variation
    arr = np.array(img)
    assert arr.max() > arr.min()


def test_generate_noise_texture_bad_mode():
    from pharos_engine.tools.texture_tools import generate_noise_texture

    with pytest.raises(ValueError):
        generate_noise_texture(mode="unknown")


def test_extract_spritesheet(tmp_path):
    from pharos_engine.tools.sprite_tools import extract_spritesheet

    sheet = Image.new("RGBA", (128, 64), (0, 0, 0, 0))
    for i in range(4):
        for j in range(2):
            color = (i * 60, j * 120, 0, 255)
            for x in range(i * 32, i * 32 + 32):
                for y in range(j * 32, j * 32 + 32):
                    sheet.putpixel((x, y), color)
    src = tmp_path / "sheet.png"
    sheet.save(str(src))
    paths = extract_spritesheet(str(src), str(tmp_path), rows=2, cols=4)
    assert len(paths) == 8
    assert all(os.path.exists(p) for p in paths)


def test_extract_spritesheet_with_names(tmp_path):
    from pharos_engine.tools.sprite_tools import extract_spritesheet

    sheet = Image.new("RGBA", (64, 32), (128, 128, 128, 255))
    src = tmp_path / "sheet.png"
    sheet.save(str(src))
    names = ["frame_a", "frame_b"]
    paths = extract_spritesheet(str(src), str(tmp_path), rows=1, cols=2, names=names)
    assert len(paths) == 2
    assert any("frame_a" in p for p in paths)
    assert any("frame_b" in p for p in paths)


def test_recolor_sprite(tmp_path):
    from pharos_engine.tools.sprite_tools import recolor_sprite

    src = tmp_path / "red.png"
    img = Image.new("RGBA", (8, 8), (255, 0, 0, 255))
    img.save(str(src))
    out = tmp_path / "recolored.png"
    recolor_sprite(str(src), str(out), hue_shift=180.0)
    result = Image.open(str(out)).convert("RGBA")
    arr = np.array(result)
    # 180° hue shift on red → cyan-ish; blue+green should now dominate
    assert arr[:, :, 0].mean() < arr[:, :, 2].mean() + 1  # R no longer dominant


def test_generate_tilt_sheet(tmp_path):
    from pharos_engine.tools.sprite_tools import generate_tilt_sheet

    src = tmp_path / "car.png"
    img = Image.new("RGBA", (64, 64), (200, 100, 50, 255))
    img.save(str(src))
    out_dir = tmp_path / "tilts"
    paths = generate_tilt_sheet(str(src), str(out_dir), directions=4, size=(64, 64))
    assert len(paths) == 4
    assert all(os.path.exists(p) for p in paths)
    # Each tile should be the correct size
    for p in paths:
        t = Image.open(p)
        assert t.size == (64, 64)


# ---------------------------------------------------------------------------
# texture_tools
# ---------------------------------------------------------------------------

def test_generate_gradient_horizontal():
    from pharos_engine.tools.texture_tools import generate_gradient

    img = generate_gradient(
        colors=[(255, 0, 0, 255), (0, 0, 255, 255)],
        width=100,
        height=10,
        direction="horizontal",
    )
    assert img.size == (100, 10)
    arr = np.array(img)
    # Left edge is red
    assert arr[5, 0, 0] > 200
    # Right edge is blue
    assert arr[5, 99, 2] > 200


def test_generate_gradient_vertical():
    from pharos_engine.tools.texture_tools import generate_gradient

    img = generate_gradient(
        colors=[(0, 255, 0, 255), (255, 0, 255, 255)],
        width=10,
        height=100,
        direction="vertical",
    )
    assert img.size == (10, 100)


def test_paint_decal(tmp_path):
    from pharos_engine.tools.texture_tools import paint_decal

    target = Image.new("RGBA", (128, 128), (100, 100, 100, 255))
    decal  = Image.new("RGBA", (20, 20), (255, 0, 0, 255))
    t_path = tmp_path / "target.png"
    d_path = tmp_path / "decal.png"
    o_path = tmp_path / "out.png"
    target.save(str(t_path))
    decal.save(str(d_path))

    result_path = paint_decal(str(t_path), str(d_path), pos=(64, 64),
                               radius=15, rotation=0.0, out_png=str(o_path))
    assert os.path.exists(result_path)
    result = Image.open(result_path).convert("RGBA")
    arr = np.array(result)
    # Centre area should contain some red pixels from the decal
    centre = arr[50:78, 50:78]
    assert centre[:, :, 0].max() > 200, "Decal red pixels not found at centre"


# ---------------------------------------------------------------------------
# audio_tools — skip gracefully if soundfile not installed
# ---------------------------------------------------------------------------

_soundfile_available = False
try:
    import soundfile as _sf
    _soundfile_available = True
except ImportError:
    pass

_skip_audio = pytest.mark.skipif(
    not _soundfile_available,
    reason="soundfile not installed",
)


def _write_wav(path, duration=0.5, samplerate=22050):
    """Helper: write a simple sine wave WAV."""
    import numpy as np
    import soundfile as sf
    t = np.linspace(0, duration, int(samplerate * duration), endpoint=False)
    data = np.sin(2 * np.pi * 440 * t).astype(np.float32)
    sf.write(str(path), data, samplerate)


@_skip_audio
def test_normalize_wav(tmp_path):
    from pharos_engine.tools.audio_tools import normalize

    in_wav = tmp_path / "in.wav"
    out_wav = tmp_path / "out.wav"
    _write_wav(in_wav)

    import soundfile as sf
    normalize(str(in_wav), str(out_wav), peak_db=-6.0)
    data, _ = sf.read(str(out_wav))
    peak = abs(data).max()
    expected = 10 ** (-6.0 / 20.0)
    assert abs(peak - expected) < 0.01, f"Peak {peak:.4f} ≠ expected {expected:.4f}"


@_skip_audio
def test_trim_silence(tmp_path):
    from pharos_engine.tools.audio_tools import trim_silence
    import soundfile as sf
    import numpy as np

    samplerate = 22050
    # 0.5s silence + 0.5s tone + 0.5s silence
    silence = np.zeros(samplerate // 2, dtype=np.float32)
    tone = np.sin(2 * np.pi * 440 * np.linspace(0, 0.5, samplerate // 2)).astype(np.float32)
    data = np.concatenate([silence, tone, silence])

    in_wav = tmp_path / "long.wav"
    out_wav = tmp_path / "trimmed.wav"
    sf.write(str(in_wav), data, samplerate)

    trim_silence(str(in_wav), str(out_wav), threshold_db=-40.0)
    trimmed, _ = sf.read(str(out_wav))
    # Trimmed should be shorter than original
    assert len(trimmed) < len(data)


@_skip_audio
def test_loop_seamless(tmp_path):
    from pharos_engine.tools.audio_tools import loop_seamless
    import soundfile as sf

    in_wav  = tmp_path / "loop_in.wav"
    out_wav = tmp_path / "loop_out.wav"
    _write_wav(in_wav, duration=1.0)

    loop_seamless(str(in_wav), str(out_wav))
    data_in,  sr_in  = sf.read(str(in_wav))
    data_out, sr_out = sf.read(str(out_wav))
    # Length should be the same; start/end should be smoothed
    assert len(data_out) == len(data_in)
    assert sr_out == sr_in
