# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 the CookVM authors
"""
CookVM CAPABILITY block parser — v2.0

Parses the structured capability declaration that a CookVM controller
sends in response to the CAPABILITY command.

v2.0: Parses INST (custom instruction) and NOTES declarations.
The CAPABILITY block is the complete, authoritative documentation for
programming the machine. A brain that reads it needs no other reference.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any
import re


@dataclass
class SensorInfo:
    name: str
    type: str = "temperature"
    unit: str = "C"
    desc: str = ""

    def summary(self) -> dict[str, str]:
        return {"name": self.name, "type": self.type, "unit": self.unit, "desc": self.desc}


@dataclass
class ActuatorInfo:
    name: str
    type: str = "binary"
    range_min: float = 0
    range_max: float = 1
    unit: str = ""
    desc: str = ""

    def summary(self) -> dict[str, Any]:
        return {
            "name": self.name, "type": self.type,
            "range": f"{self.range_min}-{self.range_max}",
            "unit": self.unit, "desc": self.desc,
        }


@dataclass
class CustomInstruction:
    """A machine-declared custom instruction from an INST line."""
    name: str
    args: list[str] = field(default_factory=list)  # e.g. ["sensor", "value"]
    desc: str = ""

    def summary(self) -> dict[str, Any]:
        return {"name": self.name, "args": self.args, "desc": self.desc}

    def usage_string(self) -> str:
        """Human-readable usage: HOLD <sensor> <value>"""
        if not self.args or self.args == ["none"]:
            return self.name
        return self.name + " " + " ".join(f"<{a}>" for a in self.args)


@dataclass
class Capability:
    """Parsed CookVM v2.0 capability block."""

    version: str = ""
    machine: str = ""
    ready: bool = False

    sensors: dict[str, SensorInfo] = field(default_factory=dict)
    actuators: dict[str, ActuatorInfo] = field(default_factory=dict)
    limits: dict[str, float] = field(default_factory=dict)
    volumes: dict[str, float] = field(default_factory=dict)
    power: dict[str, float] = field(default_factory=dict)
    features: list[str] = field(default_factory=list)

    # v2.0
    custom_instructions: dict[str, CustomInstruction] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    # ── Parsing ──

    @classmethod
    def from_lines(cls, lines: list[str]) -> "Capability":
        """Parse a list of capability declaration lines."""
        cap = cls()
        for line in lines:
            cap.feed_line(line.strip())
        return cap

    def feed_line(self, line: str) -> None:
        """Feed a single line from the capability block."""
        if not line:
            return
        tokens = line.split()
        if not tokens:
            return
        kind = tokens[0].upper()

        if kind in ("CVM", "COOKVM"):
            if len(tokens) >= 2:
                self.version = tokens[1]
            if len(tokens) >= 3:
                self.machine = tokens[2]

        elif kind == "ACTUATOR":
            if len(tokens) >= 2:
                info = ActuatorInfo(name=tokens[1])
                fields = _parse_kv_tokens(tokens[2:])
                info.type = fields.get("type", "binary")
                info.desc = fields.get("desc", "")
                info.unit = fields.get("unit", "")
                r = fields.get("range", "0-1")
                if "-" in r:
                    parts = r.split("-", 1)
                    try:
                        info.range_min = float(parts[0])
                        info.range_max = float(parts[1])
                    except ValueError:
                        pass
                self.actuators[info.name] = info

        elif kind == "SENSOR":
            if len(tokens) >= 2:
                info = SensorInfo(name=tokens[1])
                fields = _parse_kv_tokens(tokens[2:])
                info.type = fields.get("type", "temperature")
                info.unit = fields.get("unit", "C")
                info.desc = fields.get("desc", "")
                self.sensors[info.name] = info

        elif kind == "LIMIT":
            self.limits.update(_parse_kv_float(tokens[1:]))

        elif kind == "VOLUME":
            self.volumes.update(_parse_kv_float(tokens[1:]))

        elif kind == "POWER":
            self.power.update(_parse_kv_float(tokens[1:]))

        elif kind == "INST":
            # INST HOLD args=sensor,value desc=regulate_heater_to_...
            if len(tokens) >= 2:
                inst_name = tokens[1]
                fields = _parse_kv_tokens(tokens[2:])
                args_str = fields.get("args", "none")
                args = [] if args_str.lower() == "none" else args_str.split(",")
                desc = fields.get("desc", "").replace("_", " ")
                self.custom_instructions[inst_name] = CustomInstruction(
                    name=inst_name, args=args, desc=desc,
                )

        elif kind == "NOTES":
            # NOTES boiling_peaks_at_96C_on_food_sensor
            if len(tokens) >= 2:
                note_text = " ".join(tokens[1:]).replace("_", " ")
                self.notes.append(note_text)

        elif kind == "FEATURES":
            self.features = [t.lower() for t in tokens[1:]]

        # v1.1 backward compat: ignore CONTROL lines
        elif kind == "CONTROL":
            pass

        elif kind == "END_CAPABILITY":
            self.ready = True

    # ── Query helpers ──

    def has_sensor(self, name: str) -> bool:
        return name in self.sensors

    def has_actuator(self, name: str) -> bool:
        return name in self.actuators

    def has_feature(self, name: str) -> bool:
        return name.lower() in self.features

    def has_instruction(self, name: str) -> bool:
        """Check if a custom instruction is declared."""
        return name.upper() in self.custom_instructions

    def get_instruction(self, name: str) -> CustomInstruction | None:
        """Get a custom instruction by name."""
        return self.custom_instructions.get(name.upper())

    def target_setting_instructions(self) -> list[CustomInstruction]:
        """Return custom instructions that set a target on a sensor.

        These take (sensor, value) args and regulate toward a target
        without blocking. The brain must follow them with WAIT_GE to
        block until the target is reached before any timed WAIT.

        Identification: args must be ["sensor", "value"] and the desc
        must suggest regulation (regulate, maintain, hold, target, set).
        Instructions like CEILING (safety cap) also take sensor+value
        but are not target-setting — their desc says "suppress" / "limit".
        """
        _REGULATE_KEYWORDS = (
            "regulate", "maintain", "hold", "target", "set point",
            "temperature", "reach",
        )
        _SAFETY_KEYWORDS = (
            "suppress", "limit", "cap", "safety", "ceiling", "max",
        )
        result = []
        for inst in self.custom_instructions.values():
            if inst.args != ["sensor", "value"]:
                continue
            desc_lower = inst.desc.lower()
            is_regulate = any(k in desc_lower for k in _REGULATE_KEYWORDS)
            is_safety = any(k in desc_lower for k in _SAFETY_KEYWORDS)
            if is_regulate and not is_safety:
                result.append(inst)
        return result

    def preferred_process_sensor(self) -> str | None:
        keywords = ("process", "immersed", "food", "product", "core")
        for name, s in self.sensors.items():
            desc = s.desc.lower()
            if any(k in desc for k in keywords):
                return name
        return next(iter(self.sensors), None)

    def preferred_secondary_sensor(self) -> str | None:
        keywords = ("chamber", "wall", "heater", "air", "ambient")
        for name, s in self.sensors.items():
            desc = s.desc.lower()
            if any(k in desc for k in keywords):
                return name
        return None

    def preferred_heater(self) -> str | None:
        keywords = ("heat", "heater", "element", "resistive")
        for name, a in self.actuators.items():
            desc = a.desc.lower()
            if any(k in desc for k in keywords):
                return name
        return None

    def preferred_mixer(self) -> str | None:
        keywords = ("mix", "stir", "paddle", "knead", "motor", "agit")
        for name, a in self.actuators.items():
            desc = a.desc.lower()
            if any(k in desc for k in keywords):
                return name
        return None

    def resolve_sensor(self, requested: str | None) -> str | None:
        if requested and requested in self.sensors:
            return requested
        if requested:
            req = requested.lower()
            for name, s in self.sensors.items():
                if req in s.desc.lower() or req in name.lower():
                    return name
        return self.preferred_process_sensor()

    def resolve_actuator(self, requested: str | None) -> str | None:
        if requested and requested in self.actuators:
            return requested
        if requested:
            req = requested.lower()
            for name, a in self.actuators.items():
                if req in a.desc.lower() or req in name.lower():
                    return name
        return None

    # ── Serialization ──

    def summary(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "machine": self.machine,
            "ready": self.ready,
            "sensors": {n: s.summary() for n, s in self.sensors.items()},
            "actuators": {n: a.summary() for n, a in self.actuators.items()},
            "limits": self.limits,
            "volumes": self.volumes,
            "power": self.power,
            "features": self.features,
            "custom_instructions": {n: i.summary() for n, i in self.custom_instructions.items()},
            "notes": self.notes,
            "primary_sensor": self.preferred_process_sensor(),
            "secondary_sensor": self.preferred_secondary_sensor(),
            "heater": self.preferred_heater(),
            "mixer": self.preferred_mixer(),
        }

    def to_capability_json(self) -> str:
        import json
        return json.dumps(self.summary(), indent=2)

    def instruction_reference_for_llm(self) -> str:
        """
        Build a complete instruction reference from this machine's CAPABILITY.
        This is the v2.0 way: the machine teaches the brain what it can do.
        Core instructions come from the spec; custom instructions from INST.
        """
        parts = []
        parts.append(f"═══ CookVM v{self.version} Instruction Reference ═══")
        parts.append(f"Machine: {self.machine}")
        parts.append("")

        parts.append("CORE INSTRUCTIONS (universal — every CookVM 2.0 machine):")
        parts.append("  SET <actuator> <value>       Set actuator on/off or proportional value")
        parts.append("  SET_REG <actuator> <reg>      Set actuator from register value")
        parts.append("  WAIT <seconds>                Wait N seconds (actuators keep running)")
        parts.append("  WAIT_GE <sensor> <value> [timeout_s]  Wait until sensor >= value (optional timeout)")
        parts.append("  WAIT_LE <sensor> <value> [timeout_s]  Wait until sensor <= value (optional timeout)")
        parts.append("  EMIT <text>                   Send event notification (non-blocking)")
        parts.append("  PROMPT <text>                 Notify user and BLOCK until ACK received")
        parts.append("  SET_R R<n> <value>            Set register (R0-R7)")
        parts.append("  ADD R<n> <value>              Add to register")
        parts.append("  SUB R<n> <value>              Subtract from register")
        parts.append("  LOAD R<n> <sensor>            Load sensor reading into register")
        parts.append("  JMP <step>                    Unconditional jump")
        parts.append("  JGT R<n> <value> <step>       Jump if register > value")
        parts.append("  JLT R<n> <value> <step>       Jump if register < value")
        parts.append("  DJNZ R<n> <step>              Decrement register, jump if not zero")
        parts.append("  LABEL <text>                  Named marker (no runtime effect)")
        parts.append("  HALT                          End program, all actuators off")
        parts.append("  DISCONNECT <policy>           CONTINUE/PAUSE/STOP/ESTOP on link loss")
        parts.append("")

        if self.custom_instructions:
            parts.append("CUSTOM INSTRUCTIONS (this machine declares):")
            for inst in self.custom_instructions.values():
                usage = inst.usage_string()
                desc = inst.desc if inst.desc else ""
                parts.append(f"  {usage:36s} {desc}")
            parts.append("")

        parts.append("DECLARED ACTUATORS:")
        for a in self.actuators.values():
            desc = a.desc.replace("_", " ") if a.desc else ""
            parts.append(f"  {a.name} type={a.type} range={a.range_min}-{a.range_max} {desc}")

        parts.append("")
        parts.append("DECLARED SENSORS:")
        for s in self.sensors.values():
            desc = s.desc.replace("_", " ") if s.desc else ""
            parts.append(f"  {s.name} type={s.type} unit={s.unit} {desc}")

        if self.limits:
            parts.append("")
            parts.append("HARD LIMITS (machine-enforced, cannot override):")
            for k, v in self.limits.items():
                parts.append(f"  {k} = {v}")

        if self.notes:
            parts.append("")
            parts.append("MACHINE NOTES:")
            for note in self.notes:
                parts.append(f"  - {note}")

        parts.append("")
        parts.append("KEY RULES:")
        parts.append("  - Programs MUST end with HALT.")
        parts.append("  - Use only actuator/sensor names declared above.")
        parts.append("  - Custom instructions are non-blocking unless their desc says 'wait'.")
        parts.append("  - PROMPT blocks the VM until user acknowledges (brain sends ACK).")
        parts.append("  - WAIT is a one-shot trigger — once met, VM advances.")
        parts.append("  - EMIT is non-blocking. Use PROMPT when user must act before continuing.")

        # Teach WAIT_GE pattern for target-setting custom instructions.
        # A target-setting instruction takes (sensor, value) and regulates
        # toward a target without blocking. The brain must follow it with
        # WAIT_GE to block until the target is reached before any timed WAIT.
        target_insts = self.target_setting_instructions()
        if target_insts:
            names = ", ".join(inst.name for inst in target_insts)
            example = target_insts[0]
            sensor_example = next(iter(self.sensors), "sensor")
            parts.append("")
            parts.append(f"  CRITICAL — target-setting instructions ({names}):")
            parts.append(f"    These set a target but execution continues IMMEDIATELY.")
            parts.append(f"    You MUST follow with WAIT_GE on the SAME sensor to block")
            parts.append(f"    until a reachable threshold BEFORE any timed WAIT.")
            parts.append(f"    Wait INSIDE the band (below the HOLD target), with a timeout.")
            parts.append(f"    Do not WAIT_GE the exact HOLD setpoint — the band may never hit it.")
            parts.append(f"")
            parts.append(f"    WRONG:  {example.name} {sensor_example} 67 → WAIT 120")
            parts.append(f"            Timer starts before target reached!")
            parts.append(f"    WRONG:  {example.name} {sensor_example} 67 → WAIT_GE {sensor_example} 67")
            parts.append(f"            Exact setpoint may never fire (hysteresis / coast).")
            parts.append(f"    RIGHT:  {example.name} {sensor_example} 67 → WAIT_GE {sensor_example} 64 1800 → WAIT 120")
            parts.append(f"            Inside the band, with timeout, THEN the timed wait.")

        # Teach CEILING < LIMIT when both are declared.
        if self.has_instruction("CEILING") and self.limits:
            parts.append("")
            parts.append("  CRITICAL — CEILING must be BELOW hard LIMIT:")
            parts.append("    CEILING is a soft safety overlay — suppresses the heater.")
            parts.append("    LIMIT values are hard limits — exceeding them triggers a fault")
            parts.append("    or thermal fuse. NEVER set CEILING at or near the hard LIMIT.")
            parts.append("    Set CEILING appropriate to the cook, well below the LIMIT.")
            for k, v in self.limits.items():
                parts.append(f"    {k}={int(v)} is the hard limit — CEILING must be lower.")

        return "\n".join(parts)

    def all_valid_instructions(self) -> set[str]:
        """Return the full set of valid instruction names for this machine."""
        from .protocol import CORE_INSTRUCTIONS
        return CORE_INSTRUCTIONS | set(self.custom_instructions.keys())


# ── Internal helpers ──

def _parse_kv_tokens(tokens: list[str]) -> dict[str, str]:
    out = {}
    for t in tokens:
        if "=" in t:
            k, v = t.split("=", 1)
            out[k] = v
    return out


def _parse_kv_float(tokens: list[str]) -> dict[str, float]:
    out = {}
    for t in tokens:
        if "=" in t:
            k, v = t.split("=", 1)
            try:
                out[k] = float(v)
            except ValueError:
                pass
    return out
