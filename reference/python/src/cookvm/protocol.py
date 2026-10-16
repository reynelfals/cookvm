# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 the CookVM authors
"""
CookVM protocol constants — v2.0

All protocol knowledge lives here. Other modules import from this file
instead of hardcoding strings. If the spec changes, update HERE.

v2.0 changes:
- HOLD mode removed (HOLD is now a custom instruction)
- CONTROL, TARGET, TARGET_REG removed from core (now custom instructions)
- PROMPT added as core blocking instruction
- ACK added as brain→controller command
- INST / NOTES added as CAPABILITY declaration types
- STATUS core fields reduced to mode/pc/wait/fault/up; everything else dynamic
"""

# Protocol version
COOKVM_VERSION = "2.0"

# ═══════════════════════════════════════
# Modes (v2.0: HOLD removed — it's a custom instruction, not a mode)
# ═══════════════════════════════════════

MODES = {"IDLE", "DIRECT", "SEQUENCE", "PAUSED", "CALIBRATE", "TUNING", "FAULT", "ESTOP"}

COOKING_MODES = {"SEQUENCE", "PAUSED"}
INACTIVE_MODES = {"IDLE", "FAULT", "ESTOP"}

# ═══════════════════════════════════════
# Core VM Instructions (v2.0 universal — every controller MUST implement)
# ═══════════════════════════════════════

INST_SET = "SET"
INST_SET_REG = "SET_REG"

INST_WAIT = "WAIT"
INST_WAIT_GE = "WAIT_GE"
INST_WAIT_LE = "WAIT_LE"

INST_EMIT = "EMIT"
INST_PROMPT = "PROMPT"

INST_SET_R = "SET_R"
INST_ADD = "ADD"
INST_SUB = "SUB"
INST_LOAD = "LOAD"

INST_JMP = "JMP"
INST_JGT = "JGT"
INST_JLT = "JLT"
INST_DJNZ = "DJNZ"

INST_LABEL = "LABEL"
INST_HALT = "HALT"
INST_DISCONNECT = "DISCONNECT"

CORE_INSTRUCTIONS = {
    INST_SET, INST_SET_REG,
    INST_WAIT, INST_WAIT_GE, INST_WAIT_LE,
    INST_SET_R, INST_ADD, INST_SUB, INST_LOAD,
    INST_JMP, INST_JGT, INST_JLT, INST_DJNZ,
    INST_EMIT, INST_PROMPT, INST_LABEL, INST_HALT,
    INST_DISCONNECT,
}

# Backward compat alias
INSTRUCTIONS = CORE_INSTRUCTIONS

INSTANT_INSTRUCTIONS = {
    INST_SET, INST_SET_REG, INST_SET_R, INST_ADD, INST_SUB, INST_LOAD,
    INST_JMP, INST_JGT, INST_JLT, INST_DJNZ, INST_EMIT, INST_LABEL,
    INST_DISCONNECT, INST_HALT,
}

BLOCKING_INSTRUCTIONS = {INST_WAIT, INST_WAIT_GE, INST_WAIT_LE, INST_PROMPT}

# ═══════════════════════════════════════
# Common Custom Instruction Names (conventional, not required)
# ═══════════════════════════════════════

CUSTOM_HOLD = "HOLD"
CUSTOM_HOLD_OFF = "HOLD_OFF"
CUSTOM_CEILING = "CEILING"
CUSTOM_BAND = "BAND"

# ═══════════════════════════════════════
# Transport Commands (brain → controller)
# ═══════════════════════════════════════

CMD_PING = "PING"
CMD_STATUS = "STATUS"
CMD_CAPABILITY = "CAPABILITY"
CMD_ACK = "ACK"
CMD_ESTOP = "ESTOP"
CMD_CLEAR = "CLEAR"
CMD_HEARTBEAT = "HEARTBEAT"
CMD_PAUSE = "PAUSE"
CMD_RESUME = "RESUME"

CMD_PROGRAM_CLEAR = "PROGRAM CLEAR"
CMD_PROGRAM_ADD = "PROGRAM ADD"
CMD_PROGRAM_RUN = "PROGRAM RUN"
CMD_PROGRAM_STOP = "PROGRAM STOP"
CMD_PROGRAM_PAUSE = "PROGRAM PAUSE"
CMD_PROGRAM_RESUME = "PROGRAM RESUME"
CMD_PROGRAM_LIST = "PROGRAM LIST"
CMD_PROGRAM_NEXT = "PROGRAM NEXT"

CMD_MODE_IDLE = "MODE IDLE"
CMD_MODE_DIRECT = "MODE DIRECT"

CMD_CONFIG = "CONFIG"
CMD_CONFIG_SAVE = "CONFIG SAVE"
CMD_CONFIG_DEFAULTS = "CONFIG DEFAULTS"

CMD_CAL_START = "CAL START"
CMD_CAL_CAPTURE = "CAL CAPTURE"
CMD_CAL_COMPUTE = "CAL COMPUTE"
CMD_CAL_RESULT = "CAL RESULT"
CMD_CAL_APPLY = "CAL APPLY"
CMD_CAL_ABORT = "CAL ABORT"

CMD_TUNE_START = "TUNE START"
CMD_TUNE_ABORT = "TUNE ABORT"
CMD_TUNE_STATUS = "TUNE STATUS"
CMD_TUNE_RESULT = "TUNE RESULT"

CMD_VERIFY = "VERIFY"

# ═══════════════════════════════════════
# Response Message Types (controller → brain)
# ═══════════════════════════════════════

MSG_STATUS = "STATUS"
MSG_EVENT = "EVENT"
MSG_EMIT = "EMIT"
MSG_FAULT = "FAULT"
MSG_PROMPT = "PROMPT"
MSG_OK = "OK"
MSG_ERR = "ERR"
MSG_TUNE = "TUNE"
MSG_CAL = "CAL"
MSG_VERIFY = "VERIFY"

MSG_CVM_HEADER = "CVM"
MSG_COOKVM_HEADER = "COOKVM"
MSG_ACTUATOR_DECL = "ACTUATOR"
MSG_SENSOR_DECL = "SENSOR"
MSG_LIMIT_DECL = "LIMIT"
MSG_VOLUME_DECL = "VOLUME"
MSG_POWER_DECL = "POWER"
MSG_INST_DECL = "INST"
MSG_NOTES_DECL = "NOTES"
MSG_FEATURES_DECL = "FEATURES"
MSG_END_CAPABILITY = "END_CAPABILITY"

# ═══════════════════════════════════════
# STATUS Core Fields (v2.0 universal)
# ═══════════════════════════════════════

SF_MODE = "mode"
SF_PC = "pc"
SF_WAIT = "wait"
SF_FAULT = "fault"
SF_UPTIME = "up"

# Common machine-specific fields (conventional, not required)
SF_HOLD_ACTIVE = "hold_active"
SF_HOLD_TARGET = "hold_target"
SF_HOLD_SENSOR = "hold_sensor"
SF_DUTY = "duty"
SF_DELTA_T = "dT"

# ═══════════════════════════════════════
# Disconnect Policies
# ═══════════════════════════════════════

DC_CONTINUE = "CONTINUE"
DC_PAUSE = "PAUSE"
DC_STOP = "STOP"
DC_ESTOP = "ESTOP"

DISCONNECT_POLICIES = {DC_CONTINUE, DC_PAUSE, DC_STOP, DC_ESTOP}

# ═══════════════════════════════════════
# Sensor / Actuator Types
# ═══════════════════════════════════════

SENSOR_TYPE_TEMPERATURE = "temperature"
SENSOR_TYPE_PRESSURE = "pressure"
SENSOR_TYPE_MASS = "mass"
SENSOR_TYPE_HUMIDITY = "humidity"
SENSOR_TYPE_FLOW = "flow"

ACT_TYPE_BINARY = "binary"
ACT_TYPE_PROPORTIONAL = "proportional"

# ═══════════════════════════════════════
# Compliance Levels (v2.0)
# ═══════════════════════════════════════

LEVEL_1_MINIMAL = {
    INST_SET, INST_WAIT, INST_WAIT_GE, INST_WAIT_LE,
    INST_EMIT, INST_HALT, INST_LABEL,
}

LEVEL_2_STANDARD = LEVEL_1_MINIMAL | {
    INST_PROMPT, INST_SET_R, INST_ADD, INST_SUB, INST_LOAD,
    INST_JMP, INST_JGT, INST_JLT, INST_DJNZ, INST_DISCONNECT,
}

LEVEL_3_EXTENDED = LEVEL_2_STANDARD | {INST_SET_REG}
