"""VehiclePartSystem — modular vehicle parts with real physics effects.

Each installed part contributes weight, power, fuel rate, impact absorption,
elastic threshold, and headlight range to the aggregate physics stats exposed
by VehiclePartSystem. The system is pure-Python and engine-level; games wire
it to their entity in __init__ and call tick() from their physics script.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional


class PartSlot(Enum):
    ENGINE       = "engine"
    TURBO        = "turbo"
    TRANSMISSION = "transmission"
    ROLL_CAGE    = "roll_cage"
    ARMOR        = "armor"
    WEAPON_FRONT = "weapon_front"
    WEAPON_REAR  = "weapon_rear"
    WEAPON_SIDE  = "weapon_side"
    WEAPON_TOP   = "weapon_top"
    LIGHTS       = "lights"
    TIRES        = "tires"


@dataclass
class PartStats:
    """Base part data.  All physics fields are additive or multiplicative modifiers."""

    name: str
    slot: PartSlot
    weight: float = 0.0                  # kg equivalent
    power_modifier: float = 0.0          # flat power bonus (pixels/s² equivalent)
    power_multiplier: float = 1.0        # multiplicative power scaling
    fuel_rate_modifier: float = 1.0      # multiplier on fuel consumption
    impact_absorption: float = 0.0       # fraction of impulse absorbed before body
    elastic_threshold_bonus: float = 0.0 # added to DeformableLayerComponent threshold
    headlight_range_bonus: float = 0.0   # pixels added to ConeLight radius
    grip_modifier: float = 0.0           # flat grip bonus (-1..1)
    spool_time: float = 0.0              # turbo spool time (seconds)
    transmission_type: str = "auto"      # for transmission slot
    gear_count: int = 5                  # for manual/auto

    @property
    def armor_damage_reduction(self) -> float:
        """Damage reduction fraction from this part (0 = none, 1 = full immunity).

        Zero weight means no panels are present (returns 0.0).
        """
        if self.slot == PartSlot.ARMOR and self.weight > 0.0:
            panels = max(1, int(self.weight / 20.0))  # each ~20 kg = 1 panel
            return 1.0 - (0.85 ** panels)
        return 0.0


# ---------------------------------------------------------------------------
# Preset part definitions
# ---------------------------------------------------------------------------

ENGINE_STANDARD = PartStats("Standard Engine",   PartSlot.ENGINE, weight=150.0,
                            power_modifier=0.0,  power_multiplier=1.0,  fuel_rate_modifier=1.0)
ENGINE_HEAVY    = PartStats("Heavy V8",           PartSlot.ENGINE, weight=220.0,
                            power_modifier=60.0, power_multiplier=1.2,  fuel_rate_modifier=1.4)
ENGINE_LIGHT    = PartStats("Stripped Inline",    PartSlot.ENGINE, weight=90.0,
                            power_modifier=-20.0, power_multiplier=0.9, fuel_rate_modifier=0.75)

TURBO_NONE     = PartStats("No Turbo",   PartSlot.TURBO, weight=0.0)
TURBO_STANDARD = PartStats("Turbo Kit",  PartSlot.TURBO, weight=25.0,
                            power_multiplier=1.35, fuel_rate_modifier=0.9,  spool_time=1.5)
TURBO_TWIN     = PartStats("Twin Turbo", PartSlot.TURBO, weight=40.0,
                            power_multiplier=1.65, fuel_rate_modifier=1.1,  spool_time=0.8)

TRANS_AUTO   = PartStats("Auto Gearbox",   PartSlot.TRANSMISSION, weight=50.0,
                          transmission_type="auto",   power_multiplier=0.92, gear_count=5)
TRANS_MANUAL = PartStats("Manual Gearbox", PartSlot.TRANSMISSION, weight=40.0,
                          transmission_type="manual", power_multiplier=0.97, gear_count=6)
TRANS_CVT    = PartStats("CVT",            PartSlot.TRANSMISSION, weight=45.0,
                          transmission_type="cvt",    power_multiplier=0.95, gear_count=1)

ROLL_CAGE_NONE = PartStats("No Roll Cage",  PartSlot.ROLL_CAGE, weight=0.0)
ROLL_CAGE_TUBE = PartStats("Tube Roll Cage",PartSlot.ROLL_CAGE, weight=60.0,
                            impact_absorption=0.20, elastic_threshold_bonus=15.0)
ROLL_CAGE_FULL = PartStats("Full Exo-Cage", PartSlot.ROLL_CAGE, weight=95.0,
                            impact_absorption=0.38, elastic_threshold_bonus=30.0)

ARMOR_NONE   = PartStats("No Armor",           PartSlot.ARMOR, weight=0.0)
ARMOR_LIGHT  = PartStats("Scrap Panels",        PartSlot.ARMOR, weight=40.0,
                          elastic_threshold_bonus=10.0)
ARMOR_MEDIUM = PartStats("Steel Plating",       PartSlot.ARMOR, weight=100.0,
                          elastic_threshold_bonus=25.0)
ARMOR_HEAVY  = PartStats("Layered Composite",   PartSlot.ARMOR, weight=180.0,
                          elastic_threshold_bonus=45.0)

LIGHTS_NONE    = PartStats("No Lights",    PartSlot.LIGHTS, weight=0.0)
LIGHTS_BASIC   = PartStats("Headlights",   PartSlot.LIGHTS, weight=2.0,
                            headlight_range_bonus=0.0)
LIGHTS_RALLY   = PartStats("Rally Lights", PartSlot.LIGHTS, weight=5.0,
                            headlight_range_bonus=80.0)
LIGHTS_STADIUM = PartStats("Stadium Rig",  PartSlot.LIGHTS, weight=10.0,
                            headlight_range_bonus=160.0)

PART_PRESETS: Dict[str, PartStats] = {p.name: p for p in [
    ENGINE_STANDARD, ENGINE_HEAVY, ENGINE_LIGHT,
    TURBO_NONE, TURBO_STANDARD, TURBO_TWIN,
    TRANS_AUTO, TRANS_MANUAL, TRANS_CVT,
    ROLL_CAGE_NONE, ROLL_CAGE_TUBE, ROLL_CAGE_FULL,
    ARMOR_NONE, ARMOR_LIGHT, ARMOR_MEDIUM, ARMOR_HEAVY,
    LIGHTS_NONE, LIGHTS_BASIC, LIGHTS_RALLY, LIGHTS_STADIUM,
]}


# ---------------------------------------------------------------------------
# VehiclePartSystem
# ---------------------------------------------------------------------------

class VehiclePartSystem:
    """Manages installed parts and computes aggregate physics stats.

    The system is pure-Python, engine-level. The game configures which parts
    are installed via YAML; the system exposes computed physics attributes.

    Usage::

        parts = VehiclePartSystem()
        parts.install(ENGINE_HEAVY)
        parts.install(TURBO_STANDARD)
        parts.install(TRANS_MANUAL)
        # Each frame:
        parts.tick(dt, throttle=1.0)
        entity.max_speed = parts.max_speed
    """

    BASE_WEIGHT: float = 800.0         # vehicle base weight with no parts (kg eq.)
    BASE_POWER: float = 300.0          # base thrust (pixels/s²) at full throttle
    BASE_MAX_SPEED: float = 400.0      # pixels/s
    BASE_FUEL_RATE: float = 10.0       # units/second at full throttle
    BASE_ELASTIC_THRESHOLD: float = 80.0

    def __init__(self) -> None:
        self._parts: Dict[PartSlot, PartStats] = {}
        self._turbo_spool: float = 0.0    # 0..1 current spool level
        self._shift_lag: float = 0.0      # seconds remaining in gear-shift lag
        self._current_gear: int = 1
        self._fuel: float = 100.0         # 0..100

    # ------------------------------------------------------------------
    # Part management
    # ------------------------------------------------------------------

    def install(self, part: PartStats) -> None:
        """Install a part, replacing any existing part in the same slot."""
        self._parts[part.slot] = part

    def uninstall(self, slot: PartSlot) -> None:
        """Remove the part in *slot* (no-op if slot is empty)."""
        self._parts.pop(slot, None)

    def install_from_name(self, name: str) -> bool:
        """Install a part by preset name.  Returns False if name is unknown."""
        part = PART_PRESETS.get(name)
        if part is None:
            return False
        self.install(part)
        return True

    def get(self, slot: PartSlot) -> Optional[PartStats]:
        """Return the part currently installed in *slot*, or None."""
        return self._parts.get(slot)

    # ------------------------------------------------------------------
    # Per-frame update
    # ------------------------------------------------------------------

    def tick(self, dt: float, throttle: float) -> None:
        """Update time-varying state: turbo spool, shift lag, fuel consumption."""
        # Turbo spool — tracks throttle with lag
        turbo = self._parts.get(PartSlot.TURBO)
        if turbo and turbo.spool_time > 0:
            rate = dt / turbo.spool_time
            self._turbo_spool += (throttle - self._turbo_spool) * min(1.0, rate * 3.0)
        else:
            self._turbo_spool = throttle

        # Shift lag countdown
        if self._shift_lag > 0:
            self._shift_lag = max(0.0, self._shift_lag - dt)

        # Fuel drain
        if throttle > 0.1:
            self._fuel -= self.fuel_rate * throttle * dt
            self._fuel = max(0.0, self._fuel)

    # ------------------------------------------------------------------
    # Aggregate physics properties
    # ------------------------------------------------------------------

    @property
    def total_weight(self) -> float:
        """Sum of all installed part weights plus the base vehicle weight."""
        return self.BASE_WEIGHT + sum(p.weight for p in self._parts.values())

    @property
    def effective_power(self) -> float:
        """Thrust (pixels/s²) after applying all part modifiers."""
        engine = self._parts.get(PartSlot.ENGINE)
        turbo  = self._parts.get(PartSlot.TURBO)
        trans  = self._parts.get(PartSlot.TRANSMISSION)

        power = self.BASE_POWER
        if engine:
            power = (power + engine.power_modifier) * engine.power_multiplier

        # Turbo boost scaled by current spool level
        if turbo:
            turbo_mult = 1.0 + (turbo.power_multiplier - 1.0) * self._turbo_spool
            power *= turbo_mult

        # Transmission efficiency (+ shift-lag dip)
        if trans:
            trans_eff = trans.power_multiplier
            if self._shift_lag > 0:
                trans_eff *= 0.5  # momentary power dip during shift
            power *= trans_eff

        # No fuel → no power
        if self._fuel <= 0.0:
            power = 0.0

        return power

    @property
    def max_speed(self) -> float:
        """Top speed (pixels/s) proportional to effective_power / BASE_POWER."""
        return self.BASE_MAX_SPEED * (self.effective_power / self.BASE_POWER)

    @property
    def fuel_rate(self) -> float:
        """Fuel consumption (units/s) at full throttle, modified by engine and turbo."""
        engine = self._parts.get(PartSlot.ENGINE)
        turbo  = self._parts.get(PartSlot.TURBO)
        rate = self.BASE_FUEL_RATE
        if engine:
            rate *= engine.fuel_rate_modifier
        if turbo:
            rate *= turbo.fuel_rate_modifier
        return rate

    @property
    def impact_absorption(self) -> float:
        """Fraction of collision impulse absorbed before it reaches the body (0..0.7)."""
        cage  = self._parts.get(PartSlot.ROLL_CAGE)
        armor = self._parts.get(PartSlot.ARMOR)
        total = 0.0
        if cage:
            total += cage.impact_absorption
        if armor:
            # Armor adds a smaller secondary absorption
            total += armor.armor_damage_reduction * 0.15
        return min(0.7, total)

    @property
    def elastic_threshold(self) -> float:
        """DeformableLayerComponent elastic_threshold with all part bonuses applied."""
        bonus = sum(p.elastic_threshold_bonus for p in self._parts.values())
        return self.BASE_ELASTIC_THRESHOLD + bonus

    @property
    def headlight_range(self) -> float:
        """ConeLight radius: base 280 px + lights part bonus."""
        lights = self._parts.get(PartSlot.LIGHTS)
        return 280.0 + (lights.headlight_range_bonus if lights else 0.0)

    @property
    def fuel(self) -> float:
        """Current fuel level (0..100)."""
        return self._fuel

    @fuel.setter
    def fuel(self, value: float) -> None:
        self._fuel = max(0.0, min(100.0, value))

    @property
    def out_of_fuel(self) -> bool:
        """True when fuel has reached zero."""
        return self._fuel <= 0.0

    # ------------------------------------------------------------------
    # Transmission helpers
    # ------------------------------------------------------------------

    def shift_up(self) -> None:
        """Trigger a manual upshift (adds shift lag for manual transmission)."""
        trans = self._parts.get(PartSlot.TRANSMISSION)
        if trans and trans.transmission_type == "manual":
            self._current_gear = min(self._current_gear + 1, trans.gear_count)
            self._shift_lag = 0.25

    def shift_down(self) -> None:
        """Trigger a manual downshift (adds shift lag for manual transmission)."""
        trans = self._parts.get(PartSlot.TRANSMISSION)
        if trans and trans.transmission_type == "manual":
            self._current_gear = max(self._current_gear - 1, 1)
            self._shift_lag = 0.20
