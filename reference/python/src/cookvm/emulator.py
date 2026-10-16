# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 the CookVM authors
"""
CookVM Appliance Emulator — v2.0

A pure-Python thermal simulation that runs CookVM programs at
accelerated pace (default 1000x real-time). Designed for AI agent
self-improvement loops:

  1. LLM generates a CookVM program
  2. Emulator dry-runs it against the machine's CAPABILITY
  3. Returns a timeline of events, sensor curves, and detected problems
  4. Agent reviews the report and iterates if needed

The thermal model is deliberately simple — it's not trying to
predict real-world food physics precisely. It models:
  - Heater → chamber → food heat transfer with thermal lag
  - Ambient cooling (Newton's law)
  - Ceiling suppression
  - HOLD regulation (bang-bang with hysteresis)
  - PROMPT blocking (auto-ACK after configurable delay)

The emulator uses the machine's CAPABILITY (limits, power, custom
instructions) so it catches real constraint violations.
"""

from __future__ import annotations
import math
from dataclasses import dataclass, field
from typing import Any

from .capability import Capability
from .protocol import CORE_INSTRUCTIONS


# ═══════════════════════════════════════
# Thermal model parameters
# ═══════════════════════════════════════

@dataclass
class FoodParams:
    """Physical properties of the food being cooked.

    Provided by the recipe agent based on the recipe ingredients.
    Different foods have different thermal properties:
      - Water/broth: high specific heat (4.186 J/g/°C), low viscosity
      - Milk/cream: similar to water but slightly lower cp
      - Oil: lower specific heat (2.0 J/g/°C), higher boiling point
      - Dough/batter: low thermal conductivity, acts as insulator
      - Eggs in water: water dominates, eggs are small thermal mass
    """
    liquid_ml: float = 0.0         # liquid volume (water, milk, etc.)
    food_type: str = "water"       # water, dough, oil, eggs_in_water, batter, milk, broth
    food_mass_g: float = 0.0       # solid food mass (eggs, bread, etc.)
    lid_on: bool = True            # lid reduces heat loss ~3x

    @classmethod
    def from_dict(cls, d: dict) -> "FoodParams":
        if not d:
            return cls()
        return cls(
            liquid_ml=float(d.get("liquid_ml", 0)),
            food_type=str(d.get("food_type", "water")),
            food_mass_g=float(d.get("food_mass_g", 0)),
            lid_on=bool(d.get("lid_on", True)),
        )

    def total_thermal_mass_j_per_c(self) -> float:
        """Calculate total thermal mass of food contents in J/°C."""
        # Specific heat capacities (J/g/°C)
        cp_map = {
            "water": 4.186,
            "broth": 4.1,
            "milk": 3.93,
            "oil": 2.0,
            "dough": 2.5,
            "batter": 3.2,
            "eggs_in_water": 4.186,  # water dominates
        }
        cp_liquid = cp_map.get(self.food_type, 4.186)

        # Liquid: density ~1 g/ml for water-like, ~0.9 for oil
        liquid_density = 0.9 if self.food_type == "oil" else 1.0
        liquid_mass_g = self.liquid_ml * liquid_density

        # Solid food: cp ~3.0 J/g/°C average (eggs ~3.18, meat ~3.5, bread ~2.5)
        cp_solid = 3.0

        total = liquid_mass_g * cp_liquid + self.food_mass_g * cp_solid
        return max(total, 100.0)  # minimum 100 J/°C to avoid divide-by-zero


# ═══════════════════════════════════════
# Thermal model
# ═══════════════════════════════════════

@dataclass
class ThermalConfig:
    """Energy-balance thermal model for the simulated appliance.

    Derived from CAPABILITY data (the machine) + FoodParams (the recipe):

    Machine (CAPABILITY):
      POWER heater_w=750           → heater power input
      VOLUME working_ml=2200       → max capacity
      LIMIT chamber_max=160        → hard safety limits
      NOTES thermal lag Xms coast YC → auto-tune characterization

    Food (FoodParams from recipe):
      liquid_ml, food_type, food_mass_g, lid_on → thermal mass + properties

    Physics each tick:
      Q_in = heater_power * dt                              (heater energy)
      Q_loss = h_loss * (T_chamber - T_ambient) * dt        (heat to environment)
      Q_transfer = h_transfer * (T_chamber - T_food) * dt   (chamber → food)
      dT_chamber = (Q_in - Q_loss - Q_transfer) / C_chamber
      dT_food = Q_transfer / C_food
    """
    # Fixed params
    ambient_c: float = 22.0
    heater_power_w: float = 750.0
    fan_cooling_mult: float = 3.0

    # Machine thermal properties (from CAPABILITY)
    chamber_mass_j_per_c: float = 500.0    # thermal mass of chamber walls/pot

    # Food thermal properties (from FoodParams)
    food_mass_j_per_c: float = 9200.0      # thermal mass of food contents

    # Transfer coefficients (derived from auto-tune)
    chamber_loss_w_per_c: float = 5.0      # heat loss to ambient (W/°C)
    chamber_to_food_w_per_c: float = 50.0  # heat transfer chamber→food (W/°C)

    # Lid effect
    lid_on: bool = True

    @classmethod
    def from_capability(cls, cap, food: FoodParams | None = None) -> "ThermalConfig":
        """Derive thermal model from CAPABILITY + food parameters."""
        tc = cls()

        # ── Machine params from CAPABILITY ──
        tc.heater_power_w = float(cap.power.get("heater_w", 750))
        working_ml = float(cap.volumes.get("working_ml", 2200))

        # Chamber thermal mass: pot walls + structure, ~500 J/°C typical
        tc.chamber_mass_j_per_c = 500.0

        # ── Food params ──
        if food and (food.liquid_ml > 0 or food.food_mass_g > 0):
            tc.food_mass_j_per_c = food.total_thermal_mass_j_per_c()
            tc.lid_on = food.lid_on
        else:
            # Default: assume working volume of water
            tc.food_mass_j_per_c = working_ml * 4.186
            tc.lid_on = True

        # ── Parse NOTES for auto-tune data ──
        lag_ms = 0.0
        coast_c = 0.0

        for note in getattr(cap, 'notes', []):
            nl = note.lower()
            parts = nl.replace(",", " ").split()
            for i, part in enumerate(parts):
                if "lag" in part and i + 1 < len(parts):
                    val = parts[i + 1].rstrip("ms").rstrip("s")
                    try:
                        v = float(val)
                        lag_ms = v if v > 1000 else v * 1000
                    except ValueError:
                        pass
                if "coast" in part and i + 1 < len(parts):
                    val = parts[i + 1].rstrip("c").rstrip("C")
                    try:
                        coast_c = float(val)
                    except ValueError:
                        pass

        # ── Derive transfer coefficients ──

        # Chamber → food transfer: derived from thermal lag
        # lag = time for food to start responding ≈ food_mass / transfer_rate
        if lag_ms > 0:
            lag_s = lag_ms / 1000.0
            tc.chamber_to_food_w_per_c = tc.food_mass_j_per_c / lag_s
        else:
            tc.chamber_to_food_w_per_c = tc.food_mass_j_per_c / 180.0

        # Chamber → ambient loss
        # Lid on: well insulated (~2-3 W/°C)
        # Lid off: significant evaporative + convective loss (~8-12 W/°C)
        if tc.lid_on:
            tc.chamber_loss_w_per_c = tc.heater_power_w / 200.0  # ~3.75 W/°C
        else:
            tc.chamber_loss_w_per_c = tc.heater_power_w / 60.0   # ~12.5 W/°C

        # Coast overshoot calibrates chamber thermal mass
        if coast_c > 0:
            # At cutoff: stored energy in chamber = coast_c * food_mass
            # stored = chamber_mass * (T_chamber - T_food) at cutoff
            # Typical chamber-food delta at cutoff ≈ 15-25°C
            tc.chamber_mass_j_per_c = coast_c * tc.food_mass_j_per_c / 20.0

        return tc


# ═══════════════════════════════════════
# Emulator state
# ═══════════════════════════════════════

@dataclass
class EmulatorSensor:
    name: str
    type: str = "temperature"
    value: float = 22.0       # current reading (°C)
    unit: str = "C"

@dataclass
class EmulatorActuator:
    name: str
    type: str = "binary"
    value: float = 0.0
    range_min: float = 0.0
    range_max: float = 1.0


@dataclass
class TimelineEntry:
    """A snapshot at a point in simulated time."""
    t_s: float                   # simulated seconds since start
    pc: int                      # program counter
    instruction: str             # current instruction text
    sensors: dict[str, float]    # sensor values
    actuators: dict[str, float]  # actuator values
    hold_active: bool = False
    hold_target: float = 0.0
    event: str = ""              # EVENT/PROMPT text if any


@dataclass
class EmulatorProblem:
    """A detected issue in the simulated run."""
    severity: str    # "error", "warning", "info"
    time_s: float    # when it occurred
    pc: int          # program counter
    message: str     # human-readable description


@dataclass
class EmulatorResult:
    """Complete result of a simulated program run."""
    success: bool
    duration_s: float            # total simulated time
    timeline: list[TimelineEntry] = field(default_factory=list)
    problems: list[EmulatorProblem] = field(default_factory=list)
    events: list[str] = field(default_factory=list)
    final_sensors: dict[str, float] = field(default_factory=dict)
    final_actuators: dict[str, float] = field(default_factory=dict)
    halted: bool = False
    timed_out: bool = False
    steps_executed: int = 0

    def summary(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "halted": self.halted,
            "timed_out": self.timed_out,
            "duration_s": round(self.duration_s, 1),
            "duration_human": _format_duration(self.duration_s),
            "steps_executed": self.steps_executed,
            "events": self.events,
            "problems": [
                {"severity": p.severity, "time_s": round(p.time_s, 1),
                 "pc": p.pc, "message": p.message}
                for p in self.problems
            ],
            "final_sensors": {k: round(v, 1) for k, v in self.final_sensors.items()},
            "final_actuators": self.final_actuators,
            "timeline_points": len(self.timeline),
        }

    def report(self, food: FoodParams | None = None) -> str:
        """Human-readable report for LLM consumption.

        Includes simulation data so the agent can evaluate whether the
        program will actually cook the food correctly.
        """
        lines = []
        lines.append(f"═══ Emulator Report ═══")
        lines.append(f"Duration: {_format_duration(self.duration_s)}")
        lines.append(f"Steps executed: {self.steps_executed}")
        lines.append(f"Halted cleanly: {self.halted}")
        if self.timed_out:
            lines.append("TIMED OUT — program may run forever or wait on unreachable condition")

        if food and (food.liquid_ml > 0 or food.food_mass_g > 0):
            lines.append("")
            lines.append("SIMULATED FOOD:")
            if food.liquid_ml > 0:
                lines.append(f"  liquid: {food.liquid_ml:.0f}ml ({food.food_type})")
            if food.food_mass_g > 0:
                lines.append(f"  solid food: {food.food_mass_g:.0f}g")
            lines.append(f"  lid: {'on' if food.lid_on else 'off'}")
            lines.append(f"  thermal mass: {food.total_thermal_mass_j_per_c():.0f} J/°C")

        if self.problems:
            lines.append("")
            lines.append("PROBLEMS DETECTED:")
            for p in self.problems:
                icon = "ERROR" if p.severity == "error" else "WARNING" if p.severity == "warning" else "INFO"
                lines.append(f"  [{icon} at {_format_duration(p.time_s)}, pc={p.pc}] {p.message}")

        if self.events:
            lines.append("")
            lines.append("EVENTS EMITTED:")
            for e in self.events:
                lines.append(f"  - {e}")

        lines.append("")
        lines.append("FINAL STATE:")
        for k, v in self.final_sensors.items():
            lines.append(f"  {k} = {v:.1f}C")
        for k, v in self.final_actuators.items():
            lines.append(f"  {k} = {v}")

        # Peak temperatures from timeline
        if self.timeline:
            lines.append("")
            lines.append("PEAK TEMPERATURES:")
            sensor_names = set()
            for e in self.timeline:
                sensor_names.update(e.sensors.keys())
            for sname in sorted(sensor_names):
                peak = max(e.sensors.get(sname, 0) for e in self.timeline if e.sensors)
                lines.append(f"  {sname}_peak = {peak:.1f}C")

            # Timeline summary (sample every ~10% of duration)
            lines.append("")
            lines.append("TIMELINE (sensor values over time):")
            n = len(self.timeline)
            step = max(1, n // 10)
            for i in range(0, n, step):
                e = self.timeline[i]
                temps = " ".join(f"{k}={v:.1f}" for k, v in e.sensors.items())
                acts = " ".join(f"{k}={'ON' if v > 0 else 'off'}" for k, v in e.actuators.items())
                hold_info = f" HOLD={e.hold_target:.0f}" if e.hold_active else ""
                lines.append(f"  t={_format_duration(e.t_s)}: {temps} | {acts}{hold_info}")
            # Always include last entry
            if n > 0:
                e = self.timeline[-1]
                temps = " ".join(f"{k}={v:.1f}" for k, v in e.sensors.items())
                acts = " ".join(f"{k}={'ON' if v > 0 else 'off'}" for k, v in e.actuators.items())
                hold_info = f" HOLD={e.hold_target:.0f}" if e.hold_active else ""
                lines.append(f"  t={_format_duration(e.t_s)}: {temps} | {acts}{hold_info} [END]")

        if not self.problems:
            lines.append("")
            lines.append("No structural problems detected.")

        return "\n".join(lines)


# ═══════════════════════════════════════
# Emulator core
# ═══════════════════════════════════════

class Emulator:
    """Run a CookVM program against a simulated appliance.

    The emulator is a deterministic digital twin. It takes:
      - CAPABILITY: the machine (power, sensors, actuators, thermal characteristics)
      - FoodParams: the recipe (liquid volume, food type, mass, lid)

    Usage:
        emu = Emulator(capability)
        result = emu.run(ops, food=FoodParams(liquid_ml=1000, food_type="eggs_in_water"))
        print(result.report())  # agent reviews this
    """

    def __init__(
        self,
        cap,
        food: FoodParams | None = None,
        thermal: ThermalConfig | None = None,
        tick_s: float = 0.2,         # simulation tick (matches real CVM_TICK_MS)
        prompt_auto_ack_s: float = 5.0,  # auto-ACK PROMPTs after this many sim seconds
        timeline_interval_s: float = 10.0,  # record timeline every N sim seconds
    ) -> None:
        self.cap = cap
        self.food = food or FoodParams()
        self.thermal = thermal or ThermalConfig.from_capability(cap, self.food)
        self.tick_s = tick_s
        self.prompt_auto_ack_s = prompt_auto_ack_s
        self.timeline_interval_s = timeline_interval_s

    def run(
        self,
        ops: list[str],
        max_sim_s: float = 7200.0,   # 2 hour safety limit
        initial_temps: dict[str, float] | None = None,
    ) -> EmulatorResult:
        """Execute the program in simulation. Returns full results."""

        # ── Initialize state ──
        sensors: dict[str, EmulatorSensor] = {}
        for name, info in self.cap.sensors.items():
            init_temp = (initial_temps or {}).get(name, self.thermal.ambient_c)
            sensors[name] = EmulatorSensor(name=name, type=info.type,
                                           value=init_temp, unit=info.unit)

        actuators: dict[str, EmulatorActuator] = {}
        for name, info in self.cap.actuators.items():
            # Parse range string (e.g. "0-1") into min/max
            r_min, r_max = 0.0, 1.0
            range_str = getattr(info, 'range', '') or ''
            if '-' in range_str:
                try:
                    parts = range_str.split('-', 1)
                    r_min = float(parts[0])
                    r_max = float(parts[1])
                except (ValueError, IndexError):
                    pass
            actuators[name] = EmulatorActuator(
                name=name, type=info.type, value=0.0,
                range_min=r_min, range_max=r_max,
            )

        # Identify roles by semantic search
        heater_name = self.cap.preferred_heater()
        process_sensor = self.cap.preferred_process_sensor()
        secondary_sensor = self.cap.preferred_secondary_sensor()
        fan_name = None
        for aname, ainfo in self.cap.actuators.items():
            if "fan" in aname.lower() or "fan" in (ainfo.desc or "").lower():
                fan_name = aname
                break

        # ── VM state ──
        pc = 0
        waiting = False
        wait_start = 0.0
        prompt_waiting = False
        prompt_start = 0.0
        hold_active = False
        hold_target = 0.0
        hold_sensor = process_sensor or ""
        hold_band = 2.0  # °C; matches pico/cvm.c default hold_band = 2000 mdeg
        ceilings: dict[str, float] = {}  # sensor → ceiling °C
        regs: list[float] = [0.0] * 8
        dc_policy = "CONTINUE"

        sim_t = 0.0
        steps = 0
        max_jumps_tick = 10
        timeline: list[TimelineEntry] = []
        problems: list[EmulatorProblem] = []
        events: list[str] = []
        last_timeline_t = -self.timeline_interval_s

        result = EmulatorResult(
            success=False, duration_s=0.0,
            timeline=timeline, problems=problems, events=events,
        )

        # ── Pre-validation: catch malformed instructions ──
        from .protocol import CORE_INSTRUCTIONS
        valid_insts = CORE_INSTRUCTIONS | set(self.cap.custom_instructions.keys())

        for i, op in enumerate(ops):
            line = op.strip()
            if not line:
                continue
            tokens = line.split()
            inst = tokens[0].upper()

            # Check for glued tokens (e.g. "EMIT'hello" instead of "EMIT hello")
            for quote in ("'", '"'):
                if quote in inst:
                    base = inst.split(quote)[0]
                    problems.append(EmulatorProblem(
                        severity="error", time_s=0, pc=i,
                        message=f"Malformed instruction: '{line}'. "
                                f"Missing space between {base} and its argument. "
                                f"Use: {base} {line[len(base):].strip(quote)}"
                    ))
                    break

            # Check instruction is known
            clean_inst = inst.strip("'\"")
            if clean_inst not in valid_insts and clean_inst not in ("NOP",):
                problems.append(EmulatorProblem(
                    severity="error", time_s=0, pc=i,
                    message=f"Unknown instruction: '{clean_inst}'"
                ))

            # Check EMIT/PROMPT have single-token arguments (underscores, no quotes)
            if clean_inst in ("EMIT", "PROMPT") and len(tokens) >= 2:
                arg = tokens[1]
                if arg.startswith("'") or arg.startswith('"'):
                    problems.append(EmulatorProblem(
                        severity="error", time_s=0, pc=i,
                        message=f"{clean_inst} argument must not use quotes. "
                                f"Use underscores: {clean_inst} "
                                f"{'_'.join(t.strip(chr(39)+chr(34)) for t in tokens[1:])}"
                    ))
                elif len(tokens) > 2:
                    problems.append(EmulatorProblem(
                        severity="error", time_s=0, pc=i,
                        message=f"{clean_inst} takes a single token (use underscores for spaces). "
                                f"Got: '{' '.join(tokens[1:])}'. "
                                f"Use: {clean_inst} {'_'.join(tokens[1:])}"
                    ))

        # If pre-validation found errors, return immediately
        if any(p.severity == "error" for p in problems):
            result.success = False
            result.duration_s = 0
            result.steps_executed = 0
            return result

        # ── Helper: record timeline ──
        def snap(instruction: str = "", event: str = "") -> None:
            timeline.append(TimelineEntry(
                t_s=sim_t, pc=pc, instruction=instruction,
                sensors={n: round(s.value, 2) for n, s in sensors.items()},
                actuators={n: a.value for n, a in actuators.items()},
                hold_active=hold_active, hold_target=hold_target,
                event=event,
            ))

        def problem(severity: str, msg: str) -> None:
            problems.append(EmulatorProblem(severity=severity, time_s=sim_t, pc=pc, message=msg))

        def get_sensor_val(name: str) -> float | None:
            s = sensors.get(name)
            return s.value if s else None

        def set_actuator(name: str, value: float) -> None:
            a = actuators.get(name)
            if a:
                a.value = max(a.range_min, min(a.range_max, value))

        def parse_reg(token: str) -> int:
            t = token.strip().upper()
            if t.startswith("R") and len(t) == 2 and t[1].isdigit():
                return int(t[1])
            if t.isdigit():
                return int(t)
            return 0

        def parse_float_tok(token: str) -> float:
            try:
                return float(token)
            except ValueError:
                return 0.0

        # ── Main simulation loop ──
        while sim_t < max_sim_s:

            # ── Physics tick ──
            dt = self.tick_s

            heater_on = False
            if heater_name and actuators.get(heater_name):
                heater_on = actuators[heater_name].value > 0

            fan_on = False
            if fan_name and actuators.get(fan_name):
                fan_on = actuators[fan_name].value > 0

            # HOLD regulation (bang-bang)
            if hold_active and hold_sensor in sensors:
                sv = sensors[hold_sensor].value
                if sv < hold_target - hold_band:
                    if heater_name:
                        set_actuator(heater_name, actuators[heater_name].range_max)
                elif sv > hold_target + hold_band:
                    if heater_name:
                        set_actuator(heater_name, 0)
                heater_on = actuators.get(heater_name, EmulatorActuator("")).value > 0

            # Ceiling suppression
            for cname, ceil_val in ceilings.items():
                if cname in sensors and sensors[cname].value >= ceil_val:
                    if heater_name:
                        set_actuator(heater_name, 0)
                        heater_on = False

            # Heat transfer — energy balance
            if secondary_sensor and secondary_sensor in sensors:
                chamber = sensors[secondary_sensor]
                # Energy into chamber from heater (W → °C/s)
                if heater_on:
                    chamber.value += (self.thermal.heater_power_w / self.thermal.chamber_mass_j_per_c) * dt
                # Heat loss from chamber to ambient (Newton's cooling)
                cool_rate = self.thermal.chamber_loss_w_per_c
                if fan_on:
                    cool_rate *= self.thermal.fan_cooling_mult
                chamber.value -= (cool_rate * (chamber.value - self.thermal.ambient_c) / self.thermal.chamber_mass_j_per_c) * dt
                # Heat transfer from chamber to food
                if process_sensor and process_sensor in sensors:
                    food = sensors[process_sensor]
                    q_transfer = self.thermal.chamber_to_food_w_per_c * (chamber.value - food.value)
                    # Chamber loses energy to food
                    chamber.value -= (q_transfer / self.thermal.chamber_mass_j_per_c) * dt
                    # Food gains energy from chamber
                    food.value += (q_transfer / self.thermal.food_mass_j_per_c) * dt
                    # Food also loses heat to ambient (small — mostly insulated by chamber)
                    food.value -= (0.5 * (food.value - self.thermal.ambient_c) / self.thermal.food_mass_j_per_c) * dt

            elif process_sensor and process_sensor in sensors:
                # No chamber sensor — direct heating model
                food = sensors[process_sensor]
                if heater_on:
                    food.value += (self.thermal.heater_power_w / self.thermal.food_mass_j_per_c) * dt
                cool_rate = self.thermal.chamber_loss_w_per_c * 0.5
                if fan_on:
                    cool_rate *= self.thermal.fan_cooling_mult
                food.value -= (cool_rate * (food.value - self.thermal.ambient_c) / self.thermal.food_mass_j_per_c) * dt

            # Limit check
            for lname, lval in self.cap.limits.items():
                if lname.endswith("_max"):
                    sname = lname[:-4]
                    if sname in sensors and sensors[sname].value > lval:
                        problem("error", f"HARD LIMIT EXCEEDED: {sname}={sensors[sname].value:.1f}°C "
                                         f"> {lval}°C — machine would FAULT")
                        result.duration_s = sim_t
                        result.success = False
                        result.final_sensors = {n: s.value for n, s in sensors.items()}
                        result.final_actuators = {n: a.value for n, a in actuators.items()}
                        result.steps_executed = steps
                        snap("FAULT: limit exceeded")
                        return result

            # ── VM tick ──
            jumps_this_tick = 0

            while pc < len(ops) and jumps_this_tick < max_jumps_tick:

                # Blocked on PROMPT?
                if prompt_waiting:
                    if sim_t - prompt_start >= self.prompt_auto_ack_s:
                        prompt_waiting = False
                        waiting = False
                        pc += 1
                        continue
                    break  # still waiting

                # Blocked on WAIT?
                if waiting:
                    tokens = ops[pc].strip().split()
                    inst = tokens[0].upper() if tokens else ""

                    done = False
                    if inst == "WAIT":
                        wait_dur = parse_float_tok(tokens[1]) if len(tokens) > 1 else 0
                        done = (sim_t - wait_start) >= wait_dur
                    elif inst == "WAIT_GE" and len(tokens) >= 3:
                        sv = get_sensor_val(tokens[1])
                        if sv is not None:
                            done = sv >= parse_float_tok(tokens[2])
                        # Optional timeout (4th token)
                        if not done and len(tokens) >= 4:
                            timeout = parse_float_tok(tokens[3])
                            if timeout > 0 and (sim_t - wait_start) >= timeout:
                                done = True
                                snap(ops[pc].strip(), event=f"TIMEOUT:{inst}")
                                problem(
                                    "warning",
                                    f"{inst} {tokens[1]} {tokens[2]} timed out "
                                    f"after {timeout:.0f}s — advancing anyway "
                                    f"(the reference firmware emits EVENT TIMEOUT_{inst})",
                                )
                    elif inst == "WAIT_LE" and len(tokens) >= 3:
                        sv = get_sensor_val(tokens[1])
                        if sv is not None:
                            done = sv <= parse_float_tok(tokens[2])
                        # Optional timeout (4th token)
                        if not done and len(tokens) >= 4:
                            timeout = parse_float_tok(tokens[3])
                            if timeout > 0 and (sim_t - wait_start) >= timeout:
                                done = True
                                snap(ops[pc].strip(), event=f"TIMEOUT:{inst}")
                                problem(
                                    "warning",
                                    f"{inst} {tokens[1]} {tokens[2]} timed out "
                                    f"after {timeout:.0f}s — advancing anyway "
                                    f"(the reference firmware emits EVENT TIMEOUT_{inst})",
                                )
                    else:
                        done = True

                    if not done:
                        break
                    waiting = False
                    pc += 1
                    continue

                # ── Execute instruction ──
                if pc >= len(ops):
                    break

                line = ops[pc].strip()
                tokens = line.split()
                if not tokens:
                    pc += 1
                    continue
                inst = tokens[0].upper()
                steps += 1

                if inst in ("NOP", "LABEL"):
                    pc += 1

                elif inst == "SET" and len(tokens) >= 3:
                    aname = tokens[1]
                    val = parse_float_tok(tokens[2])
                    if aname not in actuators:
                        problem("error", f"SET on unknown actuator '{aname}'")
                    else:
                        set_actuator(aname, val)
                        # Last-write-wins: SET on heater releases HOLD
                        if aname == heater_name and hold_active:
                            hold_active = False
                    pc += 1

                elif inst == "SET_REG" and len(tokens) >= 3:
                    aname = tokens[1]
                    ri = parse_reg(tokens[2])
                    if aname in actuators and 0 <= ri < 8:
                        set_actuator(aname, regs[ri])
                    pc += 1

                elif inst == "WAIT" and len(tokens) >= 2:
                    waiting = True
                    wait_start = sim_t
                    # Don't advance PC — check on next tick
                    break

                elif inst in ("WAIT_GE", "WAIT_LE") and len(tokens) >= 3:
                    sname = tokens[1]
                    if sname not in sensors:
                        problem("error", f"{inst} on unknown sensor '{sname}'")
                        pc += 1
                    else:
                        waiting = True
                        wait_start = sim_t
                        break

                elif inst == "EMIT" and len(tokens) >= 2:
                    evt = tokens[1].strip("'\"")
                    events.append(evt)
                    snap(line, event=evt)
                    pc += 1

                elif inst == "PROMPT" and len(tokens) >= 2:
                    evt_text = tokens[1].strip("'\"")
                    evt = f"PROMPT:{evt_text}"
                    events.append(evt)
                    snap(line, event=evt)
                    prompt_waiting = True
                    waiting = True
                    prompt_start = sim_t
                    break

                elif inst == "HOLD" and len(tokens) >= 3:
                    sname = tokens[1]
                    target = parse_float_tok(tokens[2])
                    if sname not in sensors:
                        problem("error", f"HOLD on unknown sensor '{sname}'")
                    else:
                        hold_active = True
                        hold_sensor = sname
                        hold_target = target
                    pc += 1

                elif inst == "HOLD_OFF":
                    hold_active = False
                    if heater_name:
                        set_actuator(heater_name, 0)
                    pc += 1

                elif inst == "CEILING" and len(tokens) >= 3:
                    sname = tokens[1]
                    val = parse_float_tok(tokens[2])
                    if sname not in sensors:
                        problem("error", f"CEILING on unknown sensor '{sname}'")
                    else:
                        ceilings[sname] = val
                    pc += 1

                elif inst == "BAND" and len(tokens) >= 2:
                    hold_band = parse_float_tok(tokens[1])
                    pc += 1

                elif inst == "SET_R" and len(tokens) >= 3:
                    ri = parse_reg(tokens[1])
                    if 0 <= ri < 8:
                        regs[ri] = parse_float_tok(tokens[2])
                    pc += 1

                elif inst == "ADD" and len(tokens) >= 3:
                    ri = parse_reg(tokens[1])
                    if 0 <= ri < 8:
                        regs[ri] += parse_float_tok(tokens[2])
                    pc += 1

                elif inst == "SUB" and len(tokens) >= 3:
                    ri = parse_reg(tokens[1])
                    if 0 <= ri < 8:
                        regs[ri] -= parse_float_tok(tokens[2])
                    pc += 1

                elif inst == "LOAD" and len(tokens) >= 3:
                    ri = parse_reg(tokens[1])
                    sname = tokens[2]
                    if 0 <= ri < 8 and sname in sensors:
                        regs[ri] = sensors[sname].value
                    pc += 1

                elif inst == "JMP" and len(tokens) >= 2:
                    pc = int(parse_float_tok(tokens[1]))
                    jumps_this_tick += 1

                elif inst == "JGT" and len(tokens) >= 4:
                    ri = parse_reg(tokens[1])
                    val = parse_float_tok(tokens[2])
                    target = int(parse_float_tok(tokens[3]))
                    if 0 <= ri < 8 and regs[ri] > val:
                        pc = target
                    else:
                        pc += 1
                    jumps_this_tick += 1

                elif inst == "JLT" and len(tokens) >= 4:
                    ri = parse_reg(tokens[1])
                    val = parse_float_tok(tokens[2])
                    target = int(parse_float_tok(tokens[3]))
                    if 0 <= ri < 8 and regs[ri] < val:
                        pc = target
                    else:
                        pc += 1
                    jumps_this_tick += 1

                elif inst == "DJNZ" and len(tokens) >= 3:
                    ri = parse_reg(tokens[1])
                    target = int(parse_float_tok(tokens[2]))
                    if 0 <= ri < 8:
                        regs[ri] -= 1.0
                        if regs[ri] > 0:
                            pc = target
                        else:
                            pc += 1
                    else:
                        pc += 1
                    jumps_this_tick += 1

                elif inst == "DISCONNECT" and len(tokens) >= 2:
                    dc_policy = tokens[1].upper()
                    pc += 1

                elif inst == "HALT":
                    # All off
                    for a in actuators.values():
                        a.value = 0
                    hold_active = False
                    snap(line, event="HALT")
                    result.halted = True
                    break

                else:
                    # Unknown instruction — might be a custom instruction we
                    # don't simulate. Skip it with a warning.
                    if inst not in CORE_INSTRUCTIONS and inst not in self.cap.custom_instructions:
                        problem("warning", f"Unknown instruction '{inst}' — skipped")
                    pc += 1

            # End of program without HALT
            if pc >= len(ops) and not result.halted:
                problem("warning", "Program ended without HALT — "
                        "actuators may be left in unknown state")
                break

            if result.halted:
                break

            # Record timeline periodically
            if sim_t - last_timeline_t >= self.timeline_interval_s:
                snap(ops[min(pc, len(ops) - 1)] if pc < len(ops) else "END")
                last_timeline_t = sim_t

            sim_t += dt

        # ── Finalize ──
        if sim_t >= max_sim_s and not result.halted:
            result.timed_out = True
            blocked = ""
            if waiting and pc < len(ops):
                blocked = f" (blocked on {ops[pc].strip()!r})"
            problem(
                "error",
                f"Simulation timed out at {_format_duration(max_sim_s)} "
                f"— program may have an unreachable WAIT condition or "
                f"infinite loop{blocked}",
            )

        # Post-run analysis
        if not result.halted and not result.timed_out:
            if hold_active:
                problem("info", "HOLD still active at end of program — "
                        "regulation continues until HALT")

        for aname, act in actuators.items():
            if act.value > 0 and not result.halted:
                problem("warning", f"Actuator '{aname}' still ON at end of program "
                                   f"(value={act.value})")

        result.duration_s = sim_t
        result.steps_executed = steps
        result.final_sensors = {n: round(s.value, 1) for n, s in sensors.items()}
        result.final_actuators = {n: a.value for n, a in actuators.items()}
        result.success = result.halted and len([p for p in problems if p.severity == "error"]) == 0

        # Final snapshot
        snap("END")

        return result


# ═══════════════════════════════════════
# Convenience
# ═══════════════════════════════════════

def emulate(
    ops: list[str],
    cap,
    max_sim_s: float = 7200.0,
    initial_temps: dict[str, float] | None = None,
    food_params: dict | None = None,
) -> EmulatorResult:
    """One-shot emulation. Returns the full result.

    Args:
        ops: CookVM program instructions
        cap: Machine Capability
        max_sim_s: Maximum simulation time (safety cutoff)
        initial_temps: Override starting sensor temperatures
        food_params: Recipe food properties dict (from LLM generate_cookvm_program)
    """
    food = FoodParams.from_dict(food_params) if food_params else None
    emu = Emulator(cap, food=food)
    return emu.run(ops, max_sim_s=max_sim_s, initial_temps=initial_temps)


def _format_duration(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.0f}s"
    if seconds < 3600:
        return f"{seconds / 60:.0f}m{seconds % 60:.0f}s"
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    return f"{h}h{m:02d}m"
