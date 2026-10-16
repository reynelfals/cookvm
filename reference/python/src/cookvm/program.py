# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 the CookVM authors
"""
CookVM program builder and validator — v2.0

Build programs fluently and validate them against machine capabilities.

v2.0: CONTROL/TARGET/TARGET_REG removed from core. PROMPT added.
Custom instructions (HOLD, CEILING, BAND, etc.) are validated against
the machine's CAPABILITY declaration, not a hardcoded set.
"""

from __future__ import annotations
from typing import Any

from .protocol import CORE_INSTRUCTIONS, INST_HALT
from .capability import Capability


class ProgramBuilder:
    """Fluent builder for CookVM v2.0 programs."""

    def __init__(self) -> None:
        self.ops: list[str] = []

    # ── Actuator control ──

    def set(self, actuator: str, value: int | float) -> "ProgramBuilder":
        self.ops.append(f"SET {actuator} {value}")
        return self

    def set_reg(self, actuator: str, reg: str) -> "ProgramBuilder":
        self.ops.append(f"SET_REG {actuator} {reg}")
        return self

    # ── Waits ──

    def wait(self, seconds: int) -> "ProgramBuilder":
        self.ops.append(f"WAIT {seconds}")
        return self

    def wait_ge(self, sensor: str, value: float) -> "ProgramBuilder":
        self.ops.append(f"WAIT_GE {sensor} {value}")
        return self

    def wait_le(self, sensor: str, value: float) -> "ProgramBuilder":
        self.ops.append(f"WAIT_LE {sensor} {value}")
        return self

    # ── User interaction ──

    def emit(self, text: str) -> "ProgramBuilder":
        self.ops.append(f"EMIT {text.replace(' ', '_')}")
        return self

    def prompt(self, text: str) -> "ProgramBuilder":
        """Block VM until user acknowledges."""
        self.ops.append(f"PROMPT {text.replace(' ', '_')}")
        return self

    # ── Registers ──

    def set_r(self, reg: str, value: float) -> "ProgramBuilder":
        self.ops.append(f"SET_R {reg} {value}")
        return self

    def add(self, reg: str, value: float) -> "ProgramBuilder":
        self.ops.append(f"ADD {reg} {value}")
        return self

    def sub(self, reg: str, value: float) -> "ProgramBuilder":
        self.ops.append(f"SUB {reg} {value}")
        return self

    def load(self, reg: str, sensor: str) -> "ProgramBuilder":
        self.ops.append(f"LOAD {reg} {sensor}")
        return self

    # ── Flow control ──

    def jmp(self, step: int) -> "ProgramBuilder":
        self.ops.append(f"JMP {step}")
        return self

    def jgt(self, reg: str, value: float, step: int) -> "ProgramBuilder":
        self.ops.append(f"JGT {reg} {value} {step}")
        return self

    def jlt(self, reg: str, value: float, step: int) -> "ProgramBuilder":
        self.ops.append(f"JLT {reg} {value} {step}")
        return self

    def djnz(self, reg: str, step: int) -> "ProgramBuilder":
        self.ops.append(f"DJNZ {reg} {step}")
        return self

    # ── Program structure ──

    def label(self, text: str) -> "ProgramBuilder":
        self.ops.append(f"LABEL {text.replace(' ', '_')}")
        return self

    def halt(self) -> "ProgramBuilder":
        self.ops.append("HALT")
        return self

    def disconnect(self, policy: str) -> "ProgramBuilder":
        self.ops.append(f"DISCONNECT {policy.upper()}")
        return self

    # ── Custom instructions (generic) ──

    def custom(self, name: str, *args) -> "ProgramBuilder":
        """Add any custom instruction by name (e.g. HOLD, CEILING, BAND)."""
        parts = [name.upper()]
        for a in args:
            if isinstance(a, float):
                parts.append(f"{a}")
            else:
                parts.append(str(a))
        self.ops.append(" ".join(parts))
        return self

    # Convenience wrappers for common custom instructions

    def hold(self, sensor: str, value: float) -> "ProgramBuilder":
        return self.custom("HOLD", sensor, value)

    def hold_off(self) -> "ProgramBuilder":
        return self.custom("HOLD_OFF")

    def ceiling(self, sensor: str, value: float) -> "ProgramBuilder":
        return self.custom("CEILING", sensor, value)

    def band(self, value: float) -> "ProgramBuilder":
        return self.custom("BAND", value)

    # ── Helpers ──

    def ensure_halt(self) -> "ProgramBuilder":
        if not self.ops or self.ops[-1].upper() != "HALT":
            self.halt()
        return self

    def build(self) -> list[str]:
        return list(self.ops)

    def __len__(self) -> int:
        return len(self.ops)


def validate_ops(
    ops: list[str],
    cap: Capability | None = None,
) -> list[str]:
    """
    Validate a CookVM v2.0 program. Returns a list of error strings.
    Empty list = valid program.

    Checks:
    - All instructions are valid: either core or declared in CAPABILITY
    - Referenced sensors exist in capability (if provided)
    - Referenced actuators exist in capability (if provided)
    - Program ends with HALT
    - Jump targets are within program bounds
    - Ceiling values don't exceed declared limits
    """
    errors = []

    if not ops:
        errors.append("Program is empty")
        return errors

    # Build the set of valid instruction names
    valid_instructions = set(CORE_INSTRUCTIONS)
    if cap:
        valid_instructions |= set(cap.custom_instructions.keys())

    for i, op in enumerate(ops):
        tokens = op.strip().split()
        if not tokens:
            errors.append(f"Line {i}: empty instruction")
            continue

        inst = tokens[0].upper()

        if inst not in valid_instructions:
            errors.append(f"Line {i}: unknown instruction '{inst}'"
                         + (f" (not in core set or CAPABILITY custom instructions)" if cap else ""))
            continue

        # Validate against capability if provided
        if cap:
            # SET <actuator> — check actuator exists
            if inst == "SET" and len(tokens) >= 2:
                act = tokens[1]
                if not cap.has_actuator(act):
                    errors.append(f"Line {i}: actuator '{act}' not in CAPABILITY "
                                  f"(available: {list(cap.actuators.keys())})")

            # SET_REG <actuator> — check actuator exists
            if inst == "SET_REG" and len(tokens) >= 2:
                act = tokens[1]
                if not cap.has_actuator(act):
                    errors.append(f"Line {i}: actuator '{act}' not in CAPABILITY")

            # WAIT_GE/WAIT_LE/LOAD — check sensor exists
            if inst in ("WAIT_GE", "WAIT_LE") and len(tokens) >= 2:
                sensor = tokens[1]
                if not cap.has_sensor(sensor):
                    errors.append(f"Line {i}: sensor '{sensor}' not in CAPABILITY "
                                  f"(available: {list(cap.sensors.keys())})")

            if inst == "LOAD" and len(tokens) >= 3:
                sensor = tokens[2]
                if not cap.has_sensor(sensor):
                    errors.append(f"Line {i}: sensor '{sensor}' not in CAPABILITY")

            # Custom instruction argument validation
            if inst in cap.custom_instructions:
                ci = cap.custom_instructions[inst]
                # Check sensor/actuator arguments based on declared arg types
                for j, arg_type in enumerate(ci.args):
                    tok_idx = j + 1  # first token after instruction name
                    if tok_idx >= len(tokens):
                        break
                    if arg_type == "sensor" and not cap.has_sensor(tokens[tok_idx]):
                        errors.append(f"Line {i}: sensor '{tokens[tok_idx]}' not in CAPABILITY")
                    elif arg_type == "actuator" and not cap.has_actuator(tokens[tok_idx]):
                        errors.append(f"Line {i}: actuator '{tokens[tok_idx]}' not in CAPABILITY")

            # Check ceiling values against limits
            if inst == "CEILING" and len(tokens) >= 3:
                sensor = tokens[1]
                try:
                    ceil_val = float(tokens[2])
                    limit_key = f"{sensor}_max"
                    if limit_key in cap.limits and ceil_val > cap.limits[limit_key]:
                        errors.append(f"Line {i}: CEILING {sensor} {ceil_val} exceeds "
                                      f"machine limit {cap.limits[limit_key]}")
                except ValueError:
                    pass

        # Validate jump targets
        if inst in ("JMP", "JGT", "JLT", "DJNZ"):
            try:
                step = int(tokens[-1])
                if step < 0 or step >= len(ops):
                    errors.append(f"Line {i}: jump target {step} out of range (0-{len(ops)-1})")
            except ValueError:
                errors.append(f"Line {i}: invalid jump target '{tokens[-1]}'")

    # Program should end with HALT
    if ops and ops[-1].strip().upper() != "HALT":
        errors.append("Program does not end with HALT")

    return errors
