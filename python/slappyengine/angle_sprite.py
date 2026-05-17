from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
import math


@dataclass
class AngleEntry:
    """One keyframe in the angle blend space."""
    angle_deg: float        # canonical angle this sprite represents (e.g. 0=front, 90=right)
    layer_index: int        # index into entity.layers[] of the sprite for this angle
    state_tag: str = ""     # e.g. "damaged", "boosting", "" = base state


@dataclass
class AngleSpriteMap:
    """
    Maps rotation angles to sprite layers with optional lerp blending.

    Usage:
        amap = AngleSpriteMap(blend_mode="lerp")
        amap.add_entry(AngleEntry(0.0,   layer_index=0))   # front
        amap.add_entry(AngleEntry(90.0,  layer_index=1))   # right
        amap.add_entry(AngleEntry(180.0, layer_index=2))   # back
        amap.add_entry(AngleEntry(270.0, layer_index=3))   # left
        entity._angle_map = amap
    """
    blend_mode: str = "lerp"   # "lerp" | "snap"
    entries: list[AngleEntry] = field(default_factory=list)
    _sorted: bool = field(default=False, init=False, repr=False)

    def add_entry(self, entry: AngleEntry) -> None:
        self.entries.append(entry)
        self._sorted = False

    def clone_state(self, from_state: str, to_state: str,
                    layer_offset: int) -> None:
        """
        Copy all entries from one state tag to another, offsetting layer_index.

        Example: all base (from_state="") entries → damaged (to_state="damaged")
        entries at layer_index + layer_offset. This means you only define angles once;
        damage variants are auto-mapped using the same angular structure.
        """
        new_entries = []
        for e in self.entries:
            if e.state_tag == from_state:
                new_entries.append(
                    AngleEntry(
                        angle_deg=e.angle_deg,
                        layer_index=e.layer_index + layer_offset,
                        state_tag=to_state,
                    )
                )
        self.entries.extend(new_entries)
        self._sorted = False

    def _ensure_sorted(self) -> None:
        if not self._sorted:
            self.entries.sort(key=lambda e: e.angle_deg)
            self._sorted = True

    def _filter_entries(self, state_tag: str) -> list[AngleEntry]:
        """Return entries matching state_tag, falling back to "" if none found."""
        matched = [e for e in self.entries if e.state_tag == state_tag]
        if matched:
            return matched
        # Fall back to base state
        return [e for e in self.entries if e.state_tag == ""]

    def resolve(self, angle_deg: float,
                state_tag: str = "") -> tuple[int, int, float]:
        """
        Returns (layer_a_idx, layer_b_idx, blend_t).

        For snap mode: layer_a_idx == layer_b_idx (nearest), blend_t = 0.0.
        For lerp mode: blend between the two surrounding keyframes, blend_t in [0, 1].
        Handles circular wrap (e.g. between 350° and 10° crossing 0°).
        State filtering: only considers entries matching state_tag.
        Falls back to base state ("") if no entries for requested state_tag.
        """
        self._ensure_sorted()

        candidates = self._filter_entries(state_tag)
        if not candidates:
            # No entries at all — return a safe default
            return (0, 0, 0.0)

        # Normalize query angle to [0, 360)
        q = angle_deg % 360.0

        if len(candidates) == 1:
            idx = candidates[0].layer_index
            return (idx, idx, 0.0)

        # Sort candidates by angle_deg (they may be a subset of self.entries)
        candidates = sorted(candidates, key=lambda e: e.angle_deg)

        if self.blend_mode == "snap":
            # Find nearest entry using circular distance
            best = min(
                candidates,
                key=lambda e: min(
                    abs(q - e.angle_deg % 360.0),
                    360.0 - abs(q - e.angle_deg % 360.0),
                ),
            )
            idx = best.layer_index
            return (idx, idx, 0.0)

        # lerp mode: find the two surrounding keyframes
        # All candidate angles normalised to [0, 360)
        angles = [e.angle_deg % 360.0 for e in candidates]

        # Find the index of the first angle strictly greater than q (circular)
        # We rotate the list so the search is linear.
        n = len(angles)

        # Find the index of the entry just before q (the one whose angle <= q,
        # or the last one if q < all angles — the circular wrap case).
        a0_idx = n - 1  # default: last entry wraps around to first
        for i in range(n):
            if angles[i] > q:
                a0_idx = (i - 1) % n
                break

        a1_idx = (a0_idx + 1) % n

        a0_angle = angles[a0_idx]
        a1_angle = angles[a1_idx]

        # Unwrap a1_angle so it is always > a0_angle in the direction of travel
        if a1_angle <= a0_angle:
            a1_angle += 360.0

        # Unwrap q similarly: if q < a0_angle we've wrapped around 0°
        q_unwrapped = q
        if q_unwrapped < a0_angle:
            q_unwrapped += 360.0

        span = a1_angle - a0_angle
        if span == 0.0:
            blend_t = 0.0
        else:
            blend_t = (q_unwrapped - a0_angle) / span

        # Clamp for floating-point safety
        blend_t = max(0.0, min(1.0, blend_t))

        return (candidates[a0_idx].layer_index, candidates[a1_idx].layer_index, blend_t)

    def apply(self, entity, state_tag: str = "") -> None:
        """
        Set entity layer opacities based on current entity.rotation and state_tag.

        - Calls self.resolve(entity.rotation % 360, state_tag)
        - Sets entity.layers[layer_a_idx].opacity = 1.0 - blend_t
        - Sets entity.layers[layer_b_idx].opacity = blend_t
        - Sets all other layers' opacity = 0.0
        - If layer_a_idx == layer_b_idx (snap mode or single keyframe), opacity = 1.0, rest = 0.0
        """
        if not entity.layers:
            return

        rotation = getattr(entity, "rotation", 0.0)
        layer_a_idx, layer_b_idx, blend_t = self.resolve(rotation % 360.0, state_tag)

        # Zero all layers first
        for layer in entity.layers:
            layer.opacity = 0.0

        if layer_a_idx == layer_b_idx:
            # Snap mode or single keyframe
            if 0 <= layer_a_idx < len(entity.layers):
                entity.layers[layer_a_idx].opacity = 1.0
        else:
            if 0 <= layer_a_idx < len(entity.layers):
                entity.layers[layer_a_idx].opacity = 1.0 - blend_t
            if 0 <= layer_b_idx < len(entity.layers):
                entity.layers[layer_b_idx].opacity = blend_t


def make_angle_map_from_spritesheet(
    num_angles: int,
    layer_start: int = 0,
    blend_mode: str = "lerp",
    angle_offset: float = 0.0,
) -> AngleSpriteMap:
    """
    Convenience: create an AngleSpriteMap for num_angles equally-spaced viewpoints.

    Layers are layer_start, layer_start+1, ..., layer_start+num_angles-1.
    Angles are 0, 360/num_angles, 2*360/num_angles, ...
    angle_offset shifts all angles (e.g. if spritesheet starts at 'back' = 180°).

    Example: 8-angle spritesheet, layers 0-7, starting at front:
        make_angle_map_from_spritesheet(8, layer_start=0)
    """
    amap = AngleSpriteMap(blend_mode=blend_mode)
    step = 360.0 / num_angles
    for i in range(num_angles):
        angle = (i * step + angle_offset) % 360.0
        amap.add_entry(AngleEntry(angle_deg=angle, layer_index=layer_start + i))
    return amap
