# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 the CookVM authors
"""
cookvm — Python library for the CookVM protocol.

CookVM is an open instruction set for programmable cooking appliances.
This library provides protocol parsing, command building, and program
validation for SBC (single-board computer) applications that talk to
CookVM controllers over BLE, serial, or TCP.

v2.0: The machine is the authoritative documentation. Custom instructions
are declared in CAPABILITY via INST lines. The brain reads them generically.
"""

__version__ = "2.0.0"

from .protocol import *
from .capability import Capability, SensorInfo, ActuatorInfo, CustomInstruction
from .status import StatusParser, Status
from .commands import Commands
from .program import ProgramBuilder, validate_ops
from .spec import load_spec, load_reference_card, load_instruction_summary
from .emulator import Emulator, emulate, EmulatorResult
