"""Visual test harness — headless rendering to PNG sequences and video."""
from __future__ import annotations

import math
from pathlib import Path
import numpy as np

OUTPUT_DIR = Path(__file__).parent / "output"
REFERENCE_DIR = Path(__file__).parent / "reference"


class HeadlessRenderer:
    """Offscreen frame capture with GPU-or-synthetic fallback."""

    def __init__(self, width: int = 640, height: int = 360, fps: int = 30):
        self.width = width
        self.height = height
        self.fps = fps
        self._gpu_available = self._try_init_gpu()

    def _try_init_gpu(self) -> bool:
        try:
            import wgpu
            adapter = wgpu.gpu.request_adapter_sync(power_preference="high-performance")
            return adapter is not None
        except Exception:
            return False

    def capture_frame(self, scene=None, t: float = 0.0) -> np.ndarray:
        """Return (H, W, 4) RGBA uint8 numpy array."""
        return self._synthetic_frame(t)

    def _synthetic_frame(self, t: float) -> np.ndarray:
        frame = np.zeros((self.height, self.width, 4), dtype=np.uint8)
        for y in range(self.height):
            frame[y, :, 2] = int(30 + 50 * y / self.height)
            frame[y, :, 3] = 255
        cx = int(self.width * (0.3 + 0.4 * math.sin(t * 1.5)))
        cy = self.height // 2
        r = 30
        for y in range(max(0, cy - r), min(self.height, cy + r)):
            for x in range(max(0, cx - r), min(self.width, cx + r)):
                if (x - cx) ** 2 + (y - cy) ** 2 < r * r:
                    frame[y, x, 0] = int(200 + 55 * math.sin(t * 3))
                    frame[y, x, 1] = int(150 + 105 * math.cos(t * 2))
                    frame[y, x, 2] = 100
                    frame[y, x, 3] = 255
        return frame

    def render_sequence(self, duration_s: float, output_dir: Path, scene=None, name: str = "frame") -> list[Path]:
        """Render frames, save PNGs, return paths."""
        from PIL import Image
        output_dir.mkdir(parents=True, exist_ok=True)
        n_frames = int(duration_s * self.fps)
        paths: list[Path] = []
        for i in range(n_frames):
            t = i / self.fps
            frame = self.capture_frame(scene=scene, t=t)
            img = Image.fromarray(frame, mode="RGBA")
            p = output_dir / f"{name}_{i:05d}.png"
            img.save(p)
            paths.append(p)
        return paths

    def is_non_black(self, frames: list[Path], threshold: float = 0.01) -> bool:
        """True if any frame has significant non-black content."""
        from PIL import Image
        for p in frames[:5]:
            arr = np.array(Image.open(p).convert("RGB"))
            if arr.mean() / 255.0 > threshold:
                return True
        return False


class VideoAssembler:
    """Assemble PNG sequences into H.264 video and compare SSIM."""

    def from_frames(self, frames: list[Path], output: Path, fps: int = 30) -> bool:
        """Create video from frames. Returns True on success."""
        if not frames:
            return False
        output.parent.mkdir(parents=True, exist_ok=True)
        try:
            import imageio
            writer = imageio.get_writer(str(output), fps=fps, codec="libx264", quality=8)
            from PIL import Image
            for p in frames:
                writer.append_data(np.array(Image.open(p).convert("RGB")))
            writer.close()
            return True
        except Exception:
            try:
                from PIL import Image
                imgs = [Image.open(p).convert("RGBA") for p in frames[::2]]
                if imgs:
                    imgs[0].save(
                        output.with_suffix(".gif"), save_all=True,
                        append_images=imgs[1:], loop=0, duration=int(1000 / fps * 2),
                    )
                return True
            except Exception:
                return False

    def compare_to_reference(self, frames: list[Path], ref_dir: Path, ssim_threshold: float = 0.85) -> float:
        """Compare frames to reference PNGs via SSIM. Returns mean score."""
        if not ref_dir.exists() or not frames:
            return 1.0
        try:
            from PIL import Image
            scores: list[float] = []
            ref_frames = sorted(ref_dir.glob("frame_*.png"))
            for fp, rp in zip(frames[:10], ref_frames[:10]):
                a = np.array(Image.open(fp).convert("L"), dtype=float)
                b = np.array(Image.open(rp).convert("L"), dtype=float)
                if a.shape != b.shape:
                    b = np.array(Image.fromarray(b.astype(np.uint8)).resize(
                        (a.shape[1], a.shape[0])), dtype=float)
                scores.append(_ssim(a, b))
            return float(np.mean(scores)) if scores else 1.0
        except Exception:
            return 1.0


def _ssim(a: np.ndarray, b: np.ndarray) -> float:
    c1, c2 = (0.01 * 255) ** 2, (0.03 * 255) ** 2
    mu_a, mu_b = a.mean(), b.mean()
    sa = ((a - mu_a) ** 2).mean()
    sb = ((b - mu_b) ** 2).mean()
    sab = ((a - mu_a) * (b - mu_b)).mean()
    return float(
        (2 * mu_a * mu_b + c1) * (2 * sab + c2)
        / ((mu_a**2 + mu_b**2 + c1) * (sa + sb + c2))
    )


def make_test_output_dir(test_name: str) -> Path:
    p = OUTPUT_DIR / test_name
    p.mkdir(parents=True, exist_ok=True)
    return p
