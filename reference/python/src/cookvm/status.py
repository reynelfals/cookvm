# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 the CookVM authors
"""
CookVM STATUS line parser — v2.0

Parses STATUS lines from the controller into structured Status objects.
Also handles EVENT, FAULT, PROMPT, OK, ERR, TUNE messages.

v2.0: STATUS core fields are mode/pc/wait/fault/up. Everything else
(sensor values, actuator states, hold_active, hold_target, duty, etc.)
is dynamic and machine-specific.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any
import re

from .protocol import (
    SF_MODE, SF_PC, SF_WAIT, SF_FAULT, SF_UPTIME,
    MSG_STATUS, MSG_EVENT, MSG_EMIT, MSG_FAULT, MSG_PROMPT, MSG_OK, MSG_ERR,
    MSG_TUNE, MSG_VERIFY, MSG_CAL,
    MSG_CVM_HEADER, MSG_COOKVM_HEADER, MSG_ACTUATOR_DECL,
    MSG_SENSOR_DECL, MSG_LIMIT_DECL, MSG_VOLUME_DECL, MSG_POWER_DECL,
    MSG_INST_DECL, MSG_NOTES_DECL, MSG_FEATURES_DECL, MSG_END_CAPABILITY,
)


@dataclass
class Status:
    """Parsed STATUS message from a CookVM v2.0 controller."""
    # Core fields (universal)
    mode: str = "IDLE"
    pc: int = 0
    waiting: bool = False
    fault: str | None = None
    uptime_s: int = 0

    # Dynamic sensor/actuator values (names come from CAPABILITY)
    sensor_values: dict[str, float] = field(default_factory=dict)
    sensor_trends: dict[str, float] = field(default_factory=dict)
    actuator_values: dict[str, float] = field(default_factory=dict)

    # Machine-specific custom instruction state (hold_active, hold_target, duty, etc.)
    custom_state: dict[str, Any] = field(default_factory=dict)

    # Raw key-value pairs for anything not explicitly parsed
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class Message:
    """Parsed message from a CookVM controller."""
    kind: str
    text: str = ""
    fields: dict[str, Any] = field(default_factory=dict)


# Core STATUS field names
_CORE_STATUS_FIELDS = {SF_MODE, SF_PC, SF_WAIT, SF_FAULT, SF_UPTIME}

# Regex for key=value with optional (trend) suffix
_KV_RE = re.compile(r'(\w+)=([^\s(]+)(?:\(([^)]+)\))?')


class StatusParser:
    """Parse CookVM protocol messages."""

    @staticmethod
    def parse_kv(line: str) -> dict[str, Any]:
        result = {}
        for m in _KV_RE.finditer(line):
            key = m.group(1)
            val_str = m.group(2).replace('%', '')
            try:
                result[key] = float(val_str) if '.' in val_str else int(val_str)
            except ValueError:
                result[key] = val_str
            if m.group(3):
                trend_str = m.group(3).replace('/m', '')
                try:
                    result[key + '_trend'] = float(trend_str)
                except ValueError:
                    pass
        return result

    @classmethod
    def parse_status(cls, line: str, *, sensor_names: set[str] | None = None,
                     actuator_names: set[str] | None = None) -> Status:
        """Parse a STATUS line into a Status object.

        If sensor_names and actuator_names are provided (from CAPABILITY),
        they are used to classify dynamic fields. Otherwise, all non-core
        numeric fields go into custom_state.
        """
        fields = cls.parse_kv(line)
        s = Status()
        s.raw = dict(fields)

        # Core fields
        s.mode = str(fields.pop(SF_MODE, s.mode))
        s.pc = int(fields.pop(SF_PC, s.pc))
        s.waiting = bool(int(fields.pop(SF_WAIT, int(s.waiting))))
        s.uptime_s = int(fields.pop(SF_UPTIME, s.uptime_s))

        fault = fields.pop(SF_FAULT, None)
        if fault and str(fault) != "NONE":
            s.fault = str(fault)

        # Classify remaining fields
        sensor_names = sensor_names or set()
        actuator_names = actuator_names or set()

        for key, val in fields.items():
            if key.endswith('_trend'):
                base = key[:-6]
                if base in sensor_names and isinstance(val, (int, float)):
                    s.sensor_trends[base] = float(val)
                continue

            if key in sensor_names and isinstance(val, (int, float)):
                s.sensor_values[key] = float(val)
            elif key in actuator_names and isinstance(val, (int, float)):
                s.actuator_values[key] = float(val)
            elif isinstance(val, (int, float)):
                # Machine-specific field (hold_active, hold_target, duty, dT, etc.)
                s.custom_state[key] = val
            else:
                s.custom_state[key] = val

        return s

    @classmethod
    def parse_message(cls, line: str) -> Message:
        """Parse any protocol line into a Message object."""
        line = line.strip()
        if not line:
            return Message(kind="EMPTY")

        tokens = line.split(None, 1)
        first = tokens[0].upper()

        if first in ("STATUS", "TELEM"):
            return Message(kind=MSG_STATUS, text=line, fields=cls.parse_kv(line))

        if first == "EVENT":
            return Message(kind=MSG_EVENT, text=tokens[1] if len(tokens) > 1 else "")

        if first == "EMIT":
            return Message(kind=MSG_EMIT, text=tokens[1] if len(tokens) > 1 else "")

        if first == "FAULT":
            return Message(kind=MSG_FAULT, text=tokens[1] if len(tokens) > 1 else "")

        if first == "PROMPT":
            return Message(kind=MSG_PROMPT, text=tokens[1] if len(tokens) > 1 else "")

        if first == "OK":
            return Message(kind=MSG_OK, text=tokens[1] if len(tokens) > 1 else "")

        if first == "ERR":
            return Message(kind=MSG_ERR, text=tokens[1] if len(tokens) > 1 else "")

        if first == "TUNE":
            return Message(kind=MSG_TUNE, text=line, fields=cls.parse_kv(line))

        if first == "CAL":
            return Message(kind=MSG_CAL, text=line, fields=cls.parse_kv(line))

        if first == "VERIFY":
            return Message(kind=MSG_VERIFY, text=line, fields=cls.parse_kv(line))

        # Capability block lines
        if first in ("CVM", "COOKVM"):
            return Message(kind=MSG_CVM_HEADER, text=line,
                          fields={"version": tokens[0].split()[0] if len(tokens) > 1 else ""})
        if first == "ACTUATOR":
            return Message(kind=MSG_ACTUATOR_DECL, text=line, fields=cls.parse_kv(line))
        if first == "SENSOR":
            return Message(kind=MSG_SENSOR_DECL, text=line, fields=cls.parse_kv(line))
        if first == "LIMIT":
            return Message(kind=MSG_LIMIT_DECL, text=line, fields=cls.parse_kv(line))
        if first == "VOLUME":
            return Message(kind=MSG_VOLUME_DECL, text=line, fields=cls.parse_kv(line))
        if first == "POWER":
            return Message(kind=MSG_POWER_DECL, text=line, fields=cls.parse_kv(line))
        if first == "INST":
            return Message(kind=MSG_INST_DECL, text=line, fields=cls.parse_kv(line))
        if first == "NOTES":
            # NOTES is a single underscore-joined token
            return Message(kind=MSG_NOTES_DECL, text=tokens[1] if len(tokens) > 1 else "")
        if first == "FEATURES":
            return Message(kind=MSG_FEATURES_DECL, text=line,
                          fields={"features": line.split()[1:]})
        if first == "END_CAPABILITY":
            return Message(kind=MSG_END_CAPABILITY, text=line)

        # v1.1 backward compat: CONTROL line in capability
        if first == "CONTROL" and "=" in line:
            return Message(kind=MSG_POWER_DECL, text=line, fields=cls.parse_kv(line))

        return Message(kind="UNKNOWN", text=line)
