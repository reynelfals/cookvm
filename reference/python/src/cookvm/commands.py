# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 the CookVM authors
"""
CookVM command builder — v2.0

Builds protocol command strings from structured arguments.
Ensures commands are well-formed before sending to the controller.
"""

from .protocol import *


class Commands:
    """Builds CookVM protocol command strings."""

    # ── Basics ──

    @staticmethod
    def ping() -> str:
        return CMD_PING

    @staticmethod
    def status() -> str:
        return CMD_STATUS

    @staticmethod
    def capability() -> str:
        return CMD_CAPABILITY

    @staticmethod
    def ack() -> str:
        """Acknowledge a PROMPT — release the VM."""
        return CMD_ACK

    @staticmethod
    def estop() -> str:
        return CMD_ESTOP

    @staticmethod
    def clear() -> str:
        return CMD_CLEAR

    @staticmethod
    def heartbeat() -> str:
        return CMD_HEARTBEAT

    @staticmethod
    def pause() -> str:
        return CMD_PAUSE

    @staticmethod
    def resume() -> str:
        return CMD_RESUME

    # ── Config ──

    @staticmethod
    def config() -> str:
        return CMD_CONFIG

    @staticmethod
    def config_save() -> str:
        return CMD_CONFIG_SAVE

    @staticmethod
    def config_defaults() -> str:
        return CMD_CONFIG_DEFAULTS

    @staticmethod
    def config_set(key: str, value) -> str:
        return f"CONFIG SET {key} {value}"

    # ── Mode ──

    @staticmethod
    def mode_idle() -> str:
        return CMD_MODE_IDLE

    @staticmethod
    def mode_direct() -> str:
        return CMD_MODE_DIRECT

    # ── Custom instructions (sent as direct commands outside programs) ──

    @staticmethod
    def hold(sensor: str, target_c: float) -> str:
        """Send HOLD command (custom instruction, direct mode)."""
        return f"HOLD {sensor} {target_c:.1f}"

    @staticmethod
    def hold_off() -> str:
        """Stop temperature regulation."""
        return "HOLD_OFF"

    @staticmethod
    def ceiling(sensor: str, value: float) -> str:
        """Set soft safety ceiling on a sensor."""
        return f"CEILING {sensor} {value:.1f}"

    @staticmethod
    def band(value: float) -> str:
        """Set hysteresis band."""
        return f"BAND {value:.1f}"

    @staticmethod
    def custom_instruction(name: str, *args) -> str:
        """Send any custom instruction by name."""
        parts = [name.upper()]
        for a in args:
            if isinstance(a, float):
                parts.append(f"{a:.1f}")
            else:
                parts.append(str(a))
        return " ".join(parts)

    # ── Program management ──

    @staticmethod
    def program_clear() -> str:
        return CMD_PROGRAM_CLEAR

    @staticmethod
    def program_add(instruction: str) -> str:
        return f"{CMD_PROGRAM_ADD} {instruction}"

    @staticmethod
    def program_run() -> str:
        return CMD_PROGRAM_RUN

    @staticmethod
    def program_stop() -> str:
        return CMD_PROGRAM_STOP

    @staticmethod
    def program_list() -> str:
        return CMD_PROGRAM_LIST

    @staticmethod
    def program_next() -> str:
        """Skip current WAIT or PROMPT."""
        return CMD_PROGRAM_NEXT

    # ── Calibration ──

    @staticmethod
    def cal_start(sensor: str) -> str:
        return f"{CMD_CAL_START} {sensor}"

    @staticmethod
    def cal_capture(sensor: str, reference: float) -> str:
        return f"{CMD_CAL_CAPTURE} {sensor} {reference:.1f}"

    @staticmethod
    def cal_compute(sensor: str) -> str:
        return f"{CMD_CAL_COMPUTE} {sensor}"

    @staticmethod
    def cal_result(sensor: str) -> str:
        return f"{CMD_CAL_RESULT} {sensor}"

    @staticmethod
    def cal_apply(sensor: str) -> str:
        return f"{CMD_CAL_APPLY} {sensor}"

    @staticmethod
    def cal_abort() -> str:
        return CMD_CAL_ABORT

    # ── Tuning ──

    @staticmethod
    def tune_start() -> str:
        return CMD_TUNE_START

    @staticmethod
    def tune_abort() -> str:
        return CMD_TUNE_ABORT

    @staticmethod
    def tune_status() -> str:
        return CMD_TUNE_STATUS

    @staticmethod
    def tune_result() -> str:
        return CMD_TUNE_RESULT

    # ── Verification ──

    @staticmethod
    def verify(actuator: str) -> str:
        return f"{CMD_VERIFY} {actuator}"

    @staticmethod
    def verify_all() -> str:
        return f"{CMD_VERIFY} ALL"
