"""Audio manipulation tools.

Requires ``soundfile`` for reading/writing WAV files.  Install with:
    pip install soundfile
"""
from __future__ import annotations

from pathlib import Path


def _require_soundfile():
    try:
        import soundfile as sf
        return sf
    except ImportError:
        raise ImportError(
            "soundfile is required for audio_tools. "
            "Install it with: pip install soundfile"
        )


def trim_silence(
    in_wav: str,
    out_wav: str,
    threshold_db: float = -40.0,
) -> str:
    """Trim leading and trailing silence from a WAV file.

    Parameters
    ----------
    in_wav:
        Input WAV file path.
    out_wav:
        Output WAV file path.
    threshold_db:
        Silence threshold in dBFS.  Samples quieter than this are trimmed.

    Returns
    -------
    str
        Absolute path to the output file.
    """
    import numpy as np
    sf = _require_soundfile()

    data, samplerate = sf.read(in_wav, always_2d=True)

    threshold_linear = 10 ** (threshold_db / 20.0)

    # RMS energy per sample (across channels)
    energy = np.abs(data).max(axis=1) if data.ndim > 1 else np.abs(data)
    above = energy > threshold_linear
    indices = np.where(above)[0]

    if len(indices) == 0:
        # All silence — write empty file (1 sample)
        trimmed = data[:1]
    else:
        start = indices[0]
        end = indices[-1] + 1
        trimmed = data[start:end]

    out_file = Path(out_wav)
    out_file.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(out_file), trimmed, samplerate)
    return str(out_file.resolve())


def normalize(
    in_wav: str,
    out_wav: str,
    peak_db: float = -1.0,
) -> str:
    """Normalize the peak amplitude of a WAV file to *peak_db* dBFS.

    Parameters
    ----------
    in_wav:
        Input WAV file path.
    out_wav:
        Output WAV file path.
    peak_db:
        Target peak level in dBFS (e.g. ``-1.0``).

    Returns
    -------
    str
        Absolute path to the output file.
    """
    import numpy as np
    sf = _require_soundfile()

    data, samplerate = sf.read(in_wav, always_2d=True, dtype="float32")

    peak = np.abs(data).max()
    if peak == 0.0:
        # Silent file — pass through unchanged
        normalized = data
    else:
        target_linear = 10 ** (peak_db / 20.0)
        normalized = data * (target_linear / peak)
        # Hard clip just in case
        normalized = np.clip(normalized, -1.0, 1.0)

    out_file = Path(out_wav)
    out_file.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(out_file), normalized, samplerate, subtype="FLOAT")
    return str(out_file.resolve())


def loop_seamless(
    in_wav: str,
    out_wav: str,
) -> str:
    """Create a seamlessly loopable version of a WAV file.

    Cross-fades the end of the file back into the beginning so that the
    loop point is click-free.  The crossfade duration is 5% of the total
    file length (minimum 512 samples).

    Parameters
    ----------
    in_wav:
        Input WAV file path.
    out_wav:
        Output WAV file path.

    Returns
    -------
    str
        Absolute path to the output file.
    """
    import numpy as np
    sf = _require_soundfile()

    data, samplerate = sf.read(in_wav, always_2d=True, dtype="float32")
    n = len(data)

    fade_len = max(512, int(n * 0.05))
    if fade_len >= n:
        fade_len = n // 4

    # Fade-out applied to end, fade-in applied to start
    fade_out = np.linspace(1.0, 0.0, fade_len, dtype=np.float32)[:, np.newaxis]
    fade_in  = np.linspace(0.0, 1.0, fade_len, dtype=np.float32)[:, np.newaxis]

    result = data.copy()
    # Blend end of file with start (xfade)
    result[-fade_len:] = (data[-fade_len:] * fade_out
                          + data[:fade_len] * fade_in)

    out_file = Path(out_wav)
    out_file.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(out_file), result, samplerate, subtype="FLOAT")
    return str(out_file.resolve())
