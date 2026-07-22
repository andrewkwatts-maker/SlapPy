from __future__ import annotations

import numpy as np

_PI = float(np.pi)


def poly6_coefficient(h: float) -> float:
    return 4.0 / (_PI * (h ** 8))


def spiky_grad_coefficient(h: float) -> float:
    return -30.0 / (_PI * (h ** 5))


def poly6(r_sq: np.ndarray, h: float) -> np.ndarray:
    h2 = h * h
    diff = h2 - r_sq
    valid = (diff > 0.0) & (r_sq >= 0.0)
    coeff = poly6_coefficient(h)
    out = np.where(valid, coeff * np.power(np.maximum(diff, 0.0), 3), 0.0)
    return out.astype(np.float32, copy=False)


def poly6_scalar(r_sq: float, h: float) -> float:
    h2 = h * h
    if r_sq >= h2 or r_sq < 0.0:
        return 0.0
    diff = h2 - r_sq
    return poly6_coefficient(h) * (diff ** 3)


def spiky_grad(delta: np.ndarray, r: np.ndarray, h: float, eps: float) -> np.ndarray:
    coeff = spiky_grad_coefficient(h)
    safe_r = np.maximum(r, eps)
    inside = (r > 0.0) & (r < h)
    factor = np.where(inside, coeff * np.power(np.maximum(h - r, 0.0), 2) / safe_r, 0.0)
    return (delta * factor[:, None]).astype(np.float32, copy=False)


__all__ = [
    "poly6",
    "poly6_scalar",
    "poly6_coefficient",
    "spiky_grad",
    "spiky_grad_coefficient",
]
