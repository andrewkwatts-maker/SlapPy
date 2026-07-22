"""PhysicsEventPublisher — bridges PhysicsWorld contacts to the engine event bus.

This subsystem reads the list of :class:`ContactPair` instances that
:meth:`PhysicsWorld.step` returns each frame and republishes them as
hierarchical events on the engine-wide bus.  Optional bindings let the
publisher also play impact sounds via :class:`AudioManager` and forward
trigger-volume overlaps to :class:`TriggerSystem`.

Events published
----------------

* ``Physics.Contact`` — fires for *every* contact pair this frame.
  Payload: ``{a_name, b_name, point, normal, depth, impulse,
  material_a, material_b}``.

* ``Physics.Impact`` — fires only when the contact's impulse magnitude
  exceeds ``impact_impulse_threshold`` AND the pair was **not** in contact
  on the previous frame (so resting contacts do not spam events).  Same
  payload as ``Physics.Contact`` plus ``sound`` and ``volume``.

* ``Physics.Fragment`` — fires when a body fragments (number of live
  hulls grew between frames).  Payload:
  ``{parent_name, fragment_ids, fragment_count}``.

* ``Physics.Settled`` — fires when a body's deform controller transitions
  from ``ACTIVE``/``SETTLING`` to ``STATIC`` between frames.  Payload:
  ``{body_name}``.

The publisher works entirely from the data returned by
:meth:`PhysicsWorld.step`; it never reaches into the world's internals.
That keeps the coupling thin and makes the publisher easy to unit-test
against stubbed worlds and contact lists.
"""
from __future__ import annotations

from typing import Iterable

from pharos_engine.event_bus import publish


# Material "hardness" priority: when two materials collide we play the
# sound of the harder one (so glass-on-mud shatters rather than splats).
_MATERIAL_HARDNESS: dict[str, int] = {
    "glass": 100,
    "steel": 90,
    "metal": 85,
    "iron":  80,
    "stone": 70,
    "wood":  40,
    "mud":   10,
    "water": 5,
}


class PhysicsEventPublisher:
    """Reads PhysicsWorld contacts each step and publishes events to the
    engine's EventBus.  Optional bindings: AudioManager (plays impact
    sounds), TriggerSystem (fires triggers when bodies enter named volumes).

    Parameters
    ----------
    event_bus:
        The engine-wide :class:`EventBus` (or any object with a
        ``publish(name, **payload)`` method).  Stored for reference but
        events are routed through the module-level ``publish`` helper so
        subscribers on hierarchical prefixes still receive them.
    audio_manager:
        Optional :class:`AudioManager`.  When set, ``Physics.Impact``
        events also play the impact sound mapped from the harder
        material's name.
    trigger_system:
        Optional :class:`TriggerSystem`.  When set, each contacting body
        is checked against registered volumes via the trigger system's
        ``update``/``add`` API.
    impact_impulse_threshold:
        Minimum estimated impulse magnitude for a contact to qualify as
        an ``Impact``.  Default ``1.0`` is small enough to fire on any
        meaningful collision but large enough to ignore numerical
        chatter from resting contacts.
    """

    def __init__(
        self,
        event_bus,
        audio_manager=None,
        trigger_system=None,
        impact_impulse_threshold: float = 1.0,
    ) -> None:
        self.event_bus = event_bus
        self.audio = audio_manager
        self.triggers = trigger_system
        self.impact_threshold = float(impact_impulse_threshold)

        # Per-material impact sound name lookups (defaults included).
        self.impact_sounds: dict[str, str] = {
            "stone": "thud_stone",
            "glass": "shatter_glass",
            "metal": "clang_metal",
            "steel": "clang_metal",
            "iron":  "clang_iron",
            "wood":  "thud_wood",
            "water": "splash_water",
            "mud":   "splat_mud",
        }

        # State tracking across frames.
        # _last_frame_pairs: set of (a_hull_id, b_hull_id) pairs that were
        # touching last frame.  Lets us distinguish first-touch impacts
        # from resting contacts that span many frames.
        self._last_frame_pairs: set[tuple[int, int]] = set()
        # _last_body_count: previous live body count, used to detect
        # fragmentation.
        self._last_body_count: int = 0
        # _seen_bodies: snapshot of bodies seen at end of previous step,
        # so we can find which ids are newly minted.
        self._seen_body_ids: set[int] = set()
        # _last_states: per-body controller state from last step (only set
        # when bodies expose a .controller attribute via deform adapter).
        self._last_states: dict[int, str] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def register_impact_sound(self, material: str, sound_name: str) -> None:
        """Override the default sound mapping for *material*."""
        self.impact_sounds[material.lower()] = sound_name

    def on_step(self, world, contacts: Iterable, dt: float) -> None:
        """Publish events for the contacts this step.

        Call this once per frame, immediately after ``world.step()``.
        """
        contacts = list(contacts)
        bodies = list(getattr(world, "bodies", []) or [])
        body_for_hull = {
            getattr(b, "root_hull_id", -1): b for b in bodies
        }

        current_pairs: set[tuple[int, int]] = set()

        # ── Pass 1: per-contact Contact + Impact events ────────────────
        for pair in contacts:
            a_id = int(getattr(pair, "a", -1))
            b_id = int(getattr(pair, "b", -1))
            key = (a_id, b_id) if a_id <= b_id else (b_id, a_id)
            current_pairs.add(key)

            body_a = body_for_hull.get(a_id)
            body_b = body_for_hull.get(b_id) if b_id >= 0 else None

            a_name = self._body_name(body_a, a_id)
            b_name = self._body_name(body_b, b_id) if b_id >= 0 else "__wall__"
            mat_a = self._material_name(body_a)
            mat_b = self._material_name(body_b) if body_b is not None else None

            impulse = self._estimate_impulse(pair, body_a, body_b)

            payload = {
                "a_name":     a_name,
                "b_name":     b_name,
                "point":      tuple(getattr(pair, "point", (0.0, 0.0))),
                "normal":     tuple(getattr(pair, "normal", (0.0, 0.0))),
                "depth":      float(getattr(pair, "depth", 0.0)),
                "impulse":    float(impulse),
                "material_a": mat_a,
                "material_b": mat_b,
            }
            publish("Physics.Contact", publisher=self, **payload)

            # Impact: only for first-touch frames AND above threshold.
            first_touch = key not in self._last_frame_pairs
            if first_touch and impulse > self.impact_threshold:
                harder_mat = self._harder_material(mat_a, mat_b)
                sound_name = self.impact_sounds.get(
                    harder_mat.lower() if harder_mat else "",
                    "",
                )
                volume = max(0.0, min(1.0, impulse / 100.0))
                impact_payload = dict(payload)
                impact_payload["sound"] = sound_name
                impact_payload["volume"] = volume
                publish("Physics.Impact", publisher=self, **impact_payload)

                if self.audio is not None and sound_name:
                    try:
                        self.audio.play(sound_name, volume=volume)
                    except TypeError:
                        # AudioManager.play takes a SoundHandle in
                        # production; tests stub a simpler signature.
                        try:
                            self.audio.play(sound_name)
                        except Exception:
                            pass
                    except Exception:
                        pass

            # Trigger-system bridging — forward overlap to triggers if any.
            if self.triggers is not None and body_a is not None:
                ents = [b for b in (body_a, body_b) if b is not None]
                try:
                    self.triggers.update(ents)
                except Exception:
                    pass

        # ── Pass 2: fragment detection ─────────────────────────────────
        cur_body_ids = {getattr(b, "root_hull_id", id(b)) for b in bodies}
        new_ids = cur_body_ids - self._seen_body_ids
        if self._seen_body_ids and new_ids:
            # At least one new body appeared mid-simulation → fragmentation.
            # Heuristic for parent_name: pick the first prior body whose
            # name is non-empty.  In a richer engine the parent linkage
            # would be tracked, but for events we publish what we have.
            parent_name = ""
            for b in bodies:
                hid = getattr(b, "root_hull_id", id(b))
                if hid in self._seen_body_ids:
                    parent_name = self._body_name(b, hid)
                    break
            publish(
                "Physics.Fragment",
                publisher=self,
                parent_name=parent_name,
                fragment_ids=sorted(new_ids),
                fragment_count=len(new_ids),
            )

        # ── Pass 3: settled detection (controller STATIC transition) ──
        cur_states: dict[int, str] = {}
        for b in bodies:
            ctrl = getattr(b, "controller", None)
            state = getattr(ctrl, "state", None) if ctrl is not None else None
            state_name = getattr(state, "name", None) or getattr(state, "value", None)
            if state_name is None:
                continue
            hid = getattr(b, "root_hull_id", id(b))
            cur_states[hid] = state_name
            prev = self._last_states.get(hid)
            if prev is not None and prev != state_name and state_name.upper() == "STATIC":
                publish(
                    "Physics.Settled",
                    publisher=self,
                    body_name=self._body_name(b, hid),
                )

        # ── Update saved state for next step ───────────────────────────
        self._last_frame_pairs = current_pairs
        self._seen_body_ids = cur_body_ids
        self._last_body_count = len(cur_body_ids)
        self._last_states = cur_states

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _body_name(body, hull_id: int) -> str:
        """Best-effort human-readable name for a body."""
        if body is None:
            return f"hull_{hull_id}" if hull_id >= 0 else "__wall__"
        name = getattr(body, "name", None)
        if name:
            return str(name)
        mat = getattr(body, "material_name", None)
        if mat:
            return f"{mat}_{hull_id}"
        return f"hull_{hull_id}"

    @staticmethod
    def _material_name(body) -> str | None:
        if body is None:
            return None
        return getattr(body, "material_name", None)

    @staticmethod
    def _harder_material(mat_a: str | None, mat_b: str | None) -> str | None:
        """Return whichever material ranks higher in `_MATERIAL_HARDNESS`."""
        if mat_a is None and mat_b is None:
            return None
        if mat_a is None:
            return mat_b
        if mat_b is None:
            return mat_a
        rank_a = _MATERIAL_HARDNESS.get(mat_a.lower(), 0)
        rank_b = _MATERIAL_HARDNESS.get(mat_b.lower(), 0)
        return mat_a if rank_a >= rank_b else mat_b

    @staticmethod
    def _estimate_impulse(pair, body_a, body_b) -> float:
        """Estimate the collision impulse magnitude for *pair*.

        Uses the standard rigid-body formula:

            J ≈ (1 + e) * v_rel_n * reduced_mass

        where ``v_rel_n`` is the normal component of the relative
        velocity at the contact point and ``reduced_mass`` is
        ``(m_a * m_b) / (m_a + m_b)`` (or just ``m_a`` for body-vs-wall).

        Restitution ``e`` is folded in as 1.0 (perfectly elastic) so the
        estimate is an *upper bound* on impulse magnitude — good enough
        for threshold gating.
        """
        if body_a is None:
            return 0.0
        normal = getattr(pair, "normal", (0.0, 0.0))
        nx, ny = float(normal[0]), float(normal[1])
        va = getattr(body_a, "velocity", (0.0, 0.0))
        vax, vay = float(va[0]), float(va[1])
        if body_b is None:
            # Body-vs-wall: relative velocity is just body's velocity.
            # Normal from `pair` points from body into wall, so closing
            # speed is va · n.
            v_rel_n = vax * nx + vay * ny
            mass_a = float(getattr(body_a, "mass", 1.0))
            reduced = mass_a
        else:
            vb = getattr(body_b, "velocity", (0.0, 0.0))
            vbx, vby = float(vb[0]), float(vb[1])
            # Normal points from A → B; closing speed along n is
            # (vA - vB) · n  (positive when A moves toward B).
            v_rel_n = (vax - vbx) * nx + (vay - vby) * ny
            mass_a = float(getattr(body_a, "mass", 1.0))
            mass_b = float(getattr(body_b, "mass", 1.0))
            denom = mass_a + mass_b
            if denom <= 0.0:
                return 0.0
            reduced = (mass_a * mass_b) / denom
        # Closing-only impulse; separating contacts (negative closing
        # speed) get a zero estimate so they never qualify as impacts.
        if v_rel_n <= 0.0:
            return 0.0
        return 2.0 * v_rel_n * reduced
