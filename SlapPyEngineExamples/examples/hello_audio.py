"""SlapPyEngine — Hello Audio

Minimal demo of :mod:`slappyengine.audio_runtime` and the
``sounddevice`` fallback path.

The demo:

* Prints which backend was selected at import time (real vs stub) and,
  when real, which ``sounddevice`` device is the current default.
* Synthesises a 1-second 440 Hz sine wave (A4) as a float32 buffer at
  44100 Hz.
* Submits the buffer to ``audio_runtime.get_backend().play_buffer(...)``.
  With the real backend this plays audible sound; with the stub it is a
  no-op so the demo is fully headless-safe.
* Waits one wall-clock second (skipped with ``--no-wait`` for CI) and
  then calls ``stop_all()``.
* Prints elapsed wall-clock and ``played`` / ``stubbed`` to indicate
  which path was taken.

A ``--render`` flag rasterises a small visualisation of the synthesised
waveform: the first 200 ms zoomed in across the main plot, with the
full 1 s waveform as a small inset in the upper right corner.

Run::

    PYTHONPATH=python python examples/hello_audio.py
    PYTHONPATH=python python examples/hello_audio.py --no-wait
    PYTHONPATH=python python examples/hello_audio.py --render --out out/hello_audio.png
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Any, Dict, Tuple

import numpy as np

from slappyengine import audio_runtime


# ── Demo parameters ────────────────────────────────────────────────────────
DEFAULT_FREQ_HZ: float = 440.0  # A4
DEFAULT_SR: int = 44100
DEFAULT_DURATION_S: float = 1.0
DEFAULT_AMPLITUDE: float = 0.25  # gentle — avoids clipping if a real device runs

# ── Render parameters ──────────────────────────────────────────────────────
RENDER_W: int = 1280
RENDER_H: int = 720
RENDER_BG: Tuple[int, int, int, int] = (12, 14, 22, 255)
RENDER_FG: Tuple[int, int, int, int] = (240, 240, 240, 255)
RENDER_AXIS: Tuple[int, int, int, int] = (100, 110, 130, 255)
WAVE_COLOR: Tuple[int, int, int, int] = (90, 200, 240, 255)
INSET_COLOR: Tuple[int, int, int, int] = (240, 140, 60, 255)
INSET_BG: Tuple[int, int, int, int] = (24, 28, 40, 255)

# First 200 ms is the zoomed-in window.
ZOOM_WINDOW_S: float = 0.2


# ────────────────────────────────────────────────────────────────────────────
# Audio synthesis
# ────────────────────────────────────────────────────────────────────────────

def synthesize_sine(
    freq_hz: float = DEFAULT_FREQ_HZ,
    sample_rate: int = DEFAULT_SR,
    duration_s: float = DEFAULT_DURATION_S,
    amplitude: float = DEFAULT_AMPLITUDE,
) -> np.ndarray:
    """Return a mono float32 sine wave at ``freq_hz``.

    Output shape is ``(int(sample_rate * duration_s),)``. Amplitude is
    capped at 0.99 so a real backend never clips.
    """
    if sample_rate <= 0:
        raise ValueError(f"sample_rate must be positive, got {sample_rate}")
    if duration_s <= 0:
        raise ValueError(f"duration_s must be positive, got {duration_s}")
    n = int(round(sample_rate * duration_s))
    t = np.arange(n, dtype=np.float64) / float(sample_rate)
    amp = float(np.clip(amplitude, 0.0, 0.99))
    samples = amp * np.sin(2.0 * np.pi * freq_hz * t)
    return samples.astype(np.float32, copy=False)


# ────────────────────────────────────────────────────────────────────────────
# Backend probe
# ────────────────────────────────────────────────────────────────────────────

def describe_backend() -> Dict[str, Any]:
    """Return a dict describing the active backend.

    Keys
    ----
    ``is_real``       : bool       — True iff the real sounddevice backend.
    ``device``        : str | None — default-output device name when real.
    ``backend_class`` : str        — Python class name of the backend.
    """
    backend = audio_runtime.get_backend()
    is_real = bool(backend.is_real())
    device: Any = None
    if is_real:
        try:
            import sounddevice as sd  # type: ignore[import-not-found]

            # ``sd.default.device`` is either an int, a (in, out) tuple, or
            # the string ``None`` when no device is configured. Resolve to
            # a human-readable name when possible.
            dev = sd.default.device
            if isinstance(dev, (list, tuple)):
                # (input_index, output_index) — pick output for playback.
                out_idx = dev[1] if len(dev) > 1 else dev[0]
            else:
                out_idx = dev
            try:
                if out_idx is None or out_idx == -1:
                    device = "default"
                else:
                    info = sd.query_devices(out_idx)
                    device = info.get("name", str(out_idx))
            except Exception:
                device = str(out_idx) if out_idx is not None else "default"
        except Exception:
            device = "unknown"
    return {
        "is_real": is_real,
        "device": device,
        "backend_class": type(backend).__name__,
    }


# ────────────────────────────────────────────────────────────────────────────
# Pure-PIL renderer (no GPU dependency)
# ────────────────────────────────────────────────────────────────────────────

def _render_waveform(
    samples: np.ndarray, sample_rate: int = DEFAULT_SR
) -> np.ndarray:
    """Render the waveform to an ``(H, W, 4)`` uint8 buffer.

    The main plot shows the first 200 ms of audio. A small inset in the
    upper-right shows the full waveform for context.
    """
    from PIL import Image, ImageDraw

    img = Image.new("RGBA", (RENDER_W, RENDER_H), RENDER_BG)
    draw = ImageDraw.Draw(img, "RGBA")

    if samples.size == 0:
        return np.asarray(img, dtype=np.uint8)

    # ── Main plot: first ZOOM_WINDOW_S of audio ──────────────────────────
    margin_l, margin_r = 80, 60
    margin_t, margin_b = 60, 120
    plot_w = RENDER_W - margin_l - margin_r
    plot_h = RENDER_H - margin_t - margin_b
    x0 = margin_l
    y0 = margin_t
    x1 = x0 + plot_w
    y1 = y0 + plot_h
    mid_y = y0 + plot_h // 2

    # Axes.
    draw.rectangle([(x0 - 1, y0), (x0, y1)], fill=RENDER_AXIS)
    draw.rectangle([(x0, y1), (x1, y1 + 1)], fill=RENDER_AXIS)
    draw.line([(x0, mid_y), (x1, mid_y)], fill=RENDER_AXIS, width=1)

    zoom_n = min(int(round(ZOOM_WINDOW_S * sample_rate)), int(samples.size))
    if zoom_n > 1:
        zoom = samples[:zoom_n]
        # Map sample index → x, value → y. Use one polyline.
        peak = float(max(np.max(np.abs(zoom)), 1e-9))
        xs = (np.arange(zoom_n, dtype=np.float64) / max(zoom_n - 1, 1)) * (
            plot_w - 1
        )
        ys = -zoom.astype(np.float64) / peak  # invert: +1 → up
        # Scale to half the plot height (sine is in [-1, 1]).
        ys = ys * (plot_h * 0.45) + (plot_h * 0.5)
        pts = list(zip((x0 + xs).tolist(), (y0 + ys).tolist()))
        # Convert to integer pixel coords for deterministic rasterisation.
        pts_int = [(int(round(px)), int(round(py))) for px, py in pts]
        # Dedupe consecutive duplicates so PIL draws a clean polyline.
        cleaned = [pts_int[0]]
        for p in pts_int[1:]:
            if p != cleaned[-1]:
                cleaned.append(p)
        if len(cleaned) >= 2:
            draw.line(cleaned, fill=WAVE_COLOR, width=2)

    # ── Inset: full waveform in upper-right corner ──────────────────────
    inset_w = 320
    inset_h = 120
    inset_x = RENDER_W - margin_r - inset_w
    inset_y = 30
    inset_x1 = inset_x + inset_w
    inset_y1 = inset_y + inset_h
    draw.rectangle(
        [(inset_x, inset_y), (inset_x1, inset_y1)], fill=INSET_BG
    )
    draw.rectangle(
        [(inset_x, inset_y), (inset_x1, inset_y1)], outline=RENDER_AXIS, width=1
    )

    if samples.size > 1:
        # Downsample to ~one column per pixel; take min/max per bucket so
        # the envelope stays visible even at extreme downsample ratios.
        cols = inset_w - 2
        if cols < 2:
            cols = 2
        bucket = max(1, samples.size // cols)
        usable = (samples.size // bucket) * bucket
        if usable > 0:
            view = samples[:usable].reshape(-1, bucket)
            mins = view.min(axis=1)
            maxs = view.max(axis=1)
            peak = float(max(abs(mins).max(), abs(maxs).max(), 1e-9))
            n_cols = mins.size
            center = inset_y + inset_h / 2
            half = inset_h * 0.45
            for i in range(n_cols):
                cx = inset_x + 1 + int(round(i * (inset_w - 2) / max(n_cols - 1, 1)))
                top = center - (float(maxs[i]) / peak) * half
                bot = center - (float(mins[i]) / peak) * half
                if bot < top:
                    top, bot = bot, top
                draw.line(
                    [(cx, int(round(top))), (cx, int(round(bot)))],
                    fill=INSET_COLOR, width=1,
                )

    # Title swatch + legend swatches (no text — PIL fonts aren't always on CI).
    draw.rectangle([(margin_l, 20), (margin_l + 220, 32)], fill=RENDER_FG)
    draw.rectangle(
        [(RENDER_W - margin_r - 220, RENDER_H - 60),
         (RENDER_W - margin_r - 200, RENDER_H - 40)],
        fill=WAVE_COLOR,
    )
    draw.rectangle(
        [(RENDER_W - margin_r - 180, RENDER_H - 60),
         (RENDER_W - margin_r - 160, RENDER_H - 40)],
        fill=INSET_COLOR,
    )

    return np.asarray(img, dtype=np.uint8)


def save_render(samples: np.ndarray, out_path: Path, sample_rate: int) -> Path:
    from PIL import Image

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    arr = _render_waveform(samples, sample_rate=sample_rate)
    Image.fromarray(arr, mode="RGBA").save(out_path)
    return out_path


# ────────────────────────────────────────────────────────────────────────────
# Demo runner
# ────────────────────────────────────────────────────────────────────────────

def main(
    no_wait: bool = False,
    render: bool = False,
    out: Path | str = Path("out/hello_audio.png"),
    freq_hz: float = DEFAULT_FREQ_HZ,
    sample_rate: int = DEFAULT_SR,
    duration_s: float = DEFAULT_DURATION_S,
) -> Dict[str, Any]:
    """Run the audio demo end-to-end. Returns a summary dict for tests."""
    info = describe_backend()
    is_real = bool(info["is_real"])

    print("hello_audio")
    print(f"  backend.is_real()           : {is_real}")
    print(f"  backend class               : {info['backend_class']}")
    print(f"  sounddevice device          : {info['device']}")
    print(f"  synthesis                   : {freq_hz:.1f} Hz, {sample_rate} sr, "
          f"{duration_s:.2f} s")

    samples = synthesize_sine(
        freq_hz=freq_hz, sample_rate=sample_rate, duration_s=duration_s,
    )

    backend = audio_runtime.get_backend()
    t0 = time.perf_counter()
    backend.play_buffer(samples, sample_rate)

    if not no_wait:
        # Wait roughly the duration of the buffer. We don't strictly need
        # this for headless runs but it lets a developer actually hear the
        # tone when sounddevice is installed.
        time.sleep(duration_s)

    backend.stop_all()
    elapsed = time.perf_counter() - t0

    mode = "played" if is_real else "stubbed"
    print(f"  elapsed                     : {elapsed * 1000.0:8.2f} ms")
    print(f"  outcome                     : {mode}")

    summary: Dict[str, Any] = {
        "is_real": is_real,
        "backend_class": info["backend_class"],
        "device": info["device"],
        "freq_hz": float(freq_hz),
        "sample_rate": int(sample_rate),
        "duration_s": float(duration_s),
        "samples_len": int(samples.size),
        "elapsed_s": float(elapsed),
        "mode": mode,
        "no_wait": bool(no_wait),
    }

    if render:
        out_path = save_render(samples, Path(out), sample_rate=sample_rate)
        print(f"  rendered to                 : {out_path}")
        summary["render_path"] = str(out_path)

    return summary


# ────────────────────────────────────────────────────────────────────────────
# CLI entry point
# ────────────────────────────────────────────────────────────────────────────

def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Hello Audio — SlapPyEngine demo"
    )
    parser.add_argument(
        "--no-wait", action="store_true",
        help="skip the playback-duration wait (used by CI / tests)",
    )
    parser.add_argument(
        "--render", action="store_true",
        help="rasterise a waveform visualisation to a PNG (pure PIL)",
    )
    parser.add_argument(
        "--out", type=Path, default=Path("out/hello_audio.png"),
        help="output PNG path when --render is supplied",
    )
    parser.add_argument(
        "--freq", type=float, default=DEFAULT_FREQ_HZ,
        help=f"sine frequency in Hz (default: {DEFAULT_FREQ_HZ})",
    )
    parser.add_argument(
        "--sample-rate", type=int, default=DEFAULT_SR,
        help=f"sample rate in Hz (default: {DEFAULT_SR})",
    )
    parser.add_argument(
        "--duration", type=float, default=DEFAULT_DURATION_S,
        help=f"buffer duration in seconds (default: {DEFAULT_DURATION_S})",
    )
    return parser.parse_args(argv)


def _cli(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        main(
            no_wait=args.no_wait,
            render=args.render,
            out=args.out,
            freq_hz=args.freq,
            sample_rate=args.sample_rate,
            duration_s=args.duration,
        )
    except Exception as exc:  # pragma: no cover - defensive CLI guard
        print(f"hello_audio: error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
