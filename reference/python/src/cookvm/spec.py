# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 the CookVM authors
"""
CookVM spec loader — v2.0

v2.0 design: The spec defines core instructions. Custom instructions
come from the machine's CAPABILITY. The primary way to get an LLM
instruction reference is now Capability.instruction_reference_for_llm(),
not from the spec file. This module provides a fallback reference for
when no machine is connected yet.
"""

from pathlib import Path
import re

SPEC_PATH = Path(__file__).parent / "CookVM_Spec_v2_0.md"
# Fallback to v1.1 if v2.0 not present
if not SPEC_PATH.exists():
    SPEC_PATH = Path(__file__).parent / "CookVM_Spec_v1_1.md"


def load_spec() -> str:
    """Load the full CookVM spec as a string."""
    return SPEC_PATH.read_text("utf-8")


def _extract_section(spec: str, heading: str) -> str:
    pattern = rf'^(#{2,3}\s+.*{re.escape(heading)}.*?)$'
    match = re.search(pattern, spec, re.MULTILINE | re.IGNORECASE)
    if not match:
        return ""
    start = match.start()
    level = len(match.group(1).split()[0])
    next_heading = re.search(
        rf'^#{{{1},{level}}}\s+\S', spec[match.end():], re.MULTILINE
    )
    end = match.end() + next_heading.start() if next_heading else len(spec)
    return spec[start:end].strip()


def load_reference_card() -> str:
    """Extract the Reference Card section for LLM prompts."""
    spec = load_spec()
    section = _extract_section(spec, "Reference Card")
    if section:
        return section
    from .protocol import CORE_INSTRUCTIONS
    return "CookVM Core Instructions: " + ", ".join(sorted(CORE_INSTRUCTIONS))


def load_instruction_summary() -> str:
    """
    Build a compact core instruction summary from the spec.

    In v2.0, this is only the CORE instruction reference. Custom
    instructions are machine-specific and should come from
    Capability.instruction_reference_for_llm() at runtime.
    """
    parts = []
    parts.append("═══ CookVM v2.0 Core Instruction Reference ═══\n")

    parts.append("""CORE INSTRUCTIONS (universal — every CookVM 2.0 machine):
  SET <actuator> <value>       Set actuator on/off or proportional value
  SET_REG <actuator> <reg>     Set actuator from register value
  WAIT <seconds>               Wait N seconds (actuators keep running)
  WAIT_GE <sensor> <value> [timeout_s]  Wait until sensor >= value (optional timeout in seconds)
  WAIT_LE <sensor> <value> [timeout_s]  Wait until sensor <= value (optional timeout in seconds)
  EMIT <text>                  Send event notification (non-blocking, use_underscores)
  PROMPT <text>                Notify user and BLOCK until ACK received
  SET_R R<n> <value>           Set register (R0-R7)
  ADD R<n> <value>             Add to register
  SUB R<n> <value>             Subtract from register
  LOAD R<n> <sensor>           Load sensor reading into register
  JMP <step>                   Unconditional jump to step
  JGT R<n> <value> <step>      Jump if register > value
  JLT R<n> <value> <step>      Jump if register < value
  DJNZ R<n> <step>             Decrement register, jump if not zero
  LABEL <text>                 Named marker (no runtime effect)
  HALT                         End program, all actuators off
  DISCONNECT <policy>          CONTINUE/PAUSE/STOP/ESTOP on link loss

CUSTOM INSTRUCTIONS (machine-specific, declared via INST in CAPABILITY):
  Read the machine's CAPABILITY to learn what custom instructions it has.
  Common examples: HOLD, HOLD_OFF, CEILING, BAND, PRESSURIZE, PROMPT.
  Each machine declares them with plain-English descriptions.

KEY RULES:
  - This spec plus the machine's CAPABILITY are both required to program it.
  - Programs MUST end with HALT.
  - After HOLD <sensor> <T>, wait inside the band with a timeout
    (HOLD food 100 → WAIT_GE food 90 1800), never WAIT_GE the exact T.
  - Use only actuator/sensor names declared in CAPABILITY.
  - PROMPT blocks the VM until user acknowledges (brain sends ACK).
  - EMIT is non-blocking — use PROMPT when user must act before continuing.
  - WAIT is a one-shot trigger — once met, VM advances.
  - SET on an actuator owned by a custom instruction is last-write-wins.""")

    return "\n".join(parts)


def load_for_prompt() -> str:
    """Load the core instruction summary for LLM prompts."""
    return load_instruction_summary()
