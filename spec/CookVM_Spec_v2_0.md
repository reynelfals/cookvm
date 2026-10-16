# CookVM — Cooking Virtual Machine

## Open Instruction Set for Programmable Cooking Appliances

**Version 2.0 Draft — April 2026** (editorial clarifications September and October 2026; see `CHANGELOG.md`)

---

## 1. Purpose

CookVM defines a text-based instruction set that any cooking appliance
can execute and any AI or human can generate. It separates **what to
cook** (the program) from **how the machine works** (the controller).

A yogurt program written in CookVM runs on a bread machine, a
multicooker, a rice cooker, a pressure cooker, or any compliant controller — each
machine interprets the instructions according to its own hardware
capabilities.

The abbreviation `cvm` is used in code prefixes (e.g. `cvm_tick()`,
`cvm_state_t`) for brevity. The public name is CookVM.

### What's new in v2.0

CookVM v2.0 is built on a single insight: **the machine should be the
authoritative documentation for how to program it.**

In v1.1, the instruction set was fixed: `TARGET`, `CONTROL`, `CEILING`,
`HOLD` were all defined in the spec, and every controller had to
implement them. The LLM needed the spec document to write programs.

In v2.0, the spec defines only **universal primitives**. Everything
machine-specific — how to hold a temperature, how to pressurize —
is declared by the machine itself in the CAPABILITY block.

**What an LLM needs in order to write a program:** this specification
(the core ISA, wait semantics, PROMPT/ACK, and how to read INST /
NOTES) **plus** the target machine's CAPABILITY block (actuators,
sensors, limits, custom instructions, calibration NOTES). CAPABILITY
alone is not a programming manual. The spec alone cannot name this
machine's sensors. Both are required.

**Design goals:**
- Simple enough to fit on a microcontroller (Pico, ESP32, ATmega)
- Text-based so any LLM can generate programs
- **Self-describing** — machines declare their full instruction set
- Hardware-agnostic — programs reference capabilities, not pins
- Safe by default — machines enforce their own limits
- Turing-complete — loops, conditionals, registers
- Extensible forever — new custom instructions don't require spec changes

---

## 2. Architecture

```
┌─────────────────────────────────────────────────┐
│  BRAIN (AI, app, or human)                      │
│  Reads CAPABILITY, generates CookVM programs,   │
│  monitors telemetry, responds to PROMPT         │
└──────────────────┬──────────────────────────────┘
                   │ CookVM instructions (text)
                   │ Telemetry responses (text)
┌──────────────────┴──────────────────────────────┐
│  CONTROLLER (microcontroller or SBC)            │
│  Parses CookVM, enforces safety, drives         │
│  hardware, implements custom instructions       │
└──────────────────┬──────────────────────────────┘
                   │ Electrical signals
┌──────────────────┴──────────────────────────────┐
│  APPLIANCE (heaters, motors, valves, sensors)   │
└─────────────────────────────────────────────────┘
```

The controller is a reliable, deterministic machine. It implements
the core CookVM primitives and any machine-specific custom
instructions declared in its CAPABILITY. It does not know what food
is being cooked — it only knows how to operate its hardware safely
and report sensor readings.

---

## 3. Transport

CookVM is transport-agnostic. Instructions and responses are UTF-8
text lines terminated by newline (`\n`). Each line is one instruction
or one response. Maximum line length: 256 bytes.

Recommended transports:
- BLE Nordic UART Service (NUS)
- USB Serial
- TCP socket
- MQTT
- HTTP POST

The same instruction set works over any transport.

**BLE note:** BLE notification payloads may be limited by MTU
negotiation (typically 20–244 bytes). Controllers SHOULD place
critical fields (`mode`, `pc`, `wait`) at the start of STATUS lines
so they survive truncation on constrained transports. Controllers
SHOULD pace multi-line responses (like CAPABILITY blocks) with
small delays (~20ms) between lines to avoid overflowing shallow
notification queues.

---

## 4. Capability Declaration — The Machine Teaches the Brain

**This is the most important section of v2.0.** The CAPABILITY block
is the complete, authoritative documentation for programming the
machine. A brain that reads it needs no other reference.

### Request

```
CAPABILITY
```

### Response format

```
COOKVM 2.0 <machine_name>
ACTUATOR <name> type=<type> range=<range> [unit=<unit>] desc=<desc>
SENSOR <name> type=<type> unit=<unit> desc=<desc>
LIMIT <sensor>_max=<value> [<sensor>_min=<value>]
VOLUME <key>=<value>
POWER <key>=<value>
INST <name> args=<arglist> desc=<description>
NOTES <underscore_joined_note>
FEATURES <feature1> <feature2> ...
END_CAPABILITY
```

All lines use the same token grammar: space-separated key=value
pairs. All `desc` and `NOTES` values are single tokens — if spaces
are needed, use underscores.

### 4.1 Header

```
COOKVM 2.0 Example_BreadMachine
```

The header MUST start with `COOKVM`, followed by the protocol
version and a single-token machine name. For backward compatibility,
brains MAY accept `CVM` as a synonym for `COOKVM`.

### 4.2 Actuators

```
ACTUATOR heater type=binary range=0-1 desc=main_resistive_heater
ACTUATOR motor type=proportional range=0-100 unit=% desc=primary_mixing_motor
ACTUATOR valve type=binary range=0-1 desc=pressure_release_valve
```

Fields:
- `name` — unique identifier used in programs
- `type` — `binary` (on/off) or `proportional` (continuous range)
- `range` — valid value range, format `min-max`
- `unit` — optional unit label
- `desc` — underscore-safe semantic description for AI use

### 4.3 Sensors

```
SENSOR chamber type=temperature unit=C desc=wall_near_heater_element
SENSOR food type=temperature unit=C desc=immersed_process_sensor
SENSOR pressure type=pressure unit=bar desc=vessel_pressure
```

Fields:
- `name` — unique identifier used in programs
- `type` — `temperature`, `pressure`, `mass`, `humidity`, `flow`,
  `voltage`, `current`, or other
- `unit` — reporting unit (C, F, bar, psi, g, kg, %, L/min, V, A)
- `desc` — underscore-safe semantic description

### 4.4 Limits

```
LIMIT chamber_max=160 food_max=120 pressure_max=1.5
```

Hard safety limits the machine enforces. Programs cannot override
these. If a sensor exceeds its hard limit, the controller enters
FAULT and turns off all actuators.

### 4.5 Physical Attributes (optional)

```
VOLUME pan_ml=3000 working_ml=2200
POWER heater_w=750
```

Helps the brain scale recipes and estimate cooking times.

### 4.6 Custom Instructions (`INST`) — The Heart of v2.0

```
INST HOLD args=sensor,value desc=regulate_heater_to_maintain_sensor_temperature
INST HOLD_OFF args=none desc=stop_temperature_regulation
INST PRESSURIZE args=value desc=lock_lid_heat_until_pressure_reached
INST CEILING args=sensor,value desc=suppress_heater_if_sensor_exceeds_value
```

Each `INST` line declares one custom instruction the machine
implements. Fields:

- `name` — instruction name (uppercase convention)
- `args` — comma-separated list of argument types, or `none`
- `desc` — underscore-safe plain-English description

**Standard argument types:**
- `sensor` — name of a declared sensor
- `actuator` — name of a declared actuator
- `value` — numeric value
- `text` — user-facing text (underscore-safe)
- `reg` — register name (R0–R7)
- `step` — program line number

The brain reads these declarations to know what custom instructions
are available and how to use them. **No spec document required.**

### 4.7 Machine Notes

```
NOTES boiling_peaks_at_96C_on_food_sensor
NOTES motor_is_bread_paddle_not_whisk
NOTES thermal_lag_30s_coast_4C
NOTES auto_tune_last_run_2026_04_15
```

Underscore-joined strings describing machine-specific quirks,
calibration data, or usage guidance. The brain reads NOTES to adapt
its behavior to this specific machine. Machines SHOULD store NOTES
in non-volatile memory and update them as they learn (e.g., from
successful cooks or calibration runs).

### 4.8 Features

```
FEATURES autotune disconnect_policy sd_checkpoint telemetry_log
```

Optional protocol-level features the machine supports. Features
are for capabilities that are not single instructions — like the
ability to autotune, log telemetry to SD, or support configurable
disconnect policies.

### 4.9 Complete Example — Bread Machine

```
COOKVM 2.0 Example_BreadMachine
ACTUATOR heater type=binary range=0-1 desc=main_resistive_heater
ACTUATOR fan type=binary range=0-1 desc=air_circulation_fan
ACTUATOR motor type=binary range=0-1 desc=bread_kneading_paddle
SENSOR chamber type=temperature unit=C desc=wall_near_heater_element
SENSOR food type=temperature unit=C desc=immersed_process_sensor
LIMIT chamber_max=160 food_max=120
VOLUME pan_ml=3000 working_ml=2200
POWER heater_w=750
INST HOLD args=sensor,value desc=regulate_heater_to_maintain_sensor_temperature
INST HOLD_OFF args=none desc=stop_temperature_regulation
INST CEILING args=sensor,value desc=suppress_heater_if_sensor_exceeds_value
NOTES boiling_peaks_at_96C_on_food_sensor
NOTES motor_is_bread_paddle_not_whisk
FEATURES autotune disconnect_policy
END_CAPABILITY
```

### 4.10 Complete Example — Pressure Cooker

```
COOKVM 2.0 Example_PressureCooker
ACTUATOR heater type=proportional range=0-100 unit=% desc=bottom_element
ACTUATOR valve type=binary range=0-1 desc=pressure_release_valve
ACTUATOR lid_lock type=binary range=0-1 desc=safety_lid_lock
SENSOR food type=temperature unit=C desc=bottom_sensor
SENSOR pressure type=pressure unit=bar desc=vessel_pressure
LIMIT food_max=180 pressure_max=1.5
INST HOLD args=sensor,value desc=regulate_heater_to_maintain_sensor_at_value
INST HOLD_OFF args=none desc=stop_regulation
INST PRESSURIZE args=value desc=lock_lid_heat_until_target_bar_reached_then_hold
INST DEPRESSURIZE args=none desc=open_valve_wait_until_safe_unlock_lid
INST CEILING args=sensor,value desc=soft_safety_limit_per_sensor
NOTES never_open_lid_while_pressurized
FEATURES autotune disconnect_policy
END_CAPABILITY
```

Different machines, different custom instructions, **same core
primitives**. An LLM that has read this spec uses each machine's
CAPABILITY to learn the custom names (`HOLD` vs `PRESSURIZE`) and
the local NOTES. `PROMPT` is a core instruction (§5.3), not an INST.

### 4.11 When to Re-query CAPABILITY

Brains SHOULD query `CAPABILITY` on connect and after any connection
drop. Machines MAY update their NOTES between queries (e.g., after
a successful cook or calibration), so re-querying keeps the brain's
knowledge current.

---

## 5. Core Instruction Set

These instructions are **universal** — every CookVM v2.0 controller
MUST implement them. Everything else is machine-declared via INST.

### 5.1 Actuator Control

```
SET <actuator> <value>
```

Set an actuator to a value. The controller validates the value
against the declared range. Out-of-range values are rejected with
an `ERR` response.

```
SET heater 1
SET motor 50
SET fan 0
```

**SET_REG** — set actuator from a register value:
```
SET_REG <actuator> <reg>
```

**Precedence rule:** if a custom instruction (like HOLD) is actively
driving an actuator, a direct SET to that actuator is **last-write-
wins**: the SET takes control, releasing the custom instruction's
hold on that actuator. The controller reports this transition via
a `EVENT` message (e.g., `EVENT HOLD_RELEASED_BY_SET`).

### 5.2 Blocking Waits

```
WAIT <seconds>                        # Wait N seconds
WAIT_GE <sensor> <value> [timeout_s]  # Wait until sensor >= value (optional timeout)
WAIT_LE <sensor> <value> [timeout_s]  # Wait until sensor <= value (optional timeout)
```

Execution pauses at a WAIT until the condition is met. All other
machine operations continue during the wait: active custom
instructions keep running, safety checks run, actuators maintain
their state.

**WAIT is a one-shot trigger**: once the condition is met for a
single tick, the VM advances. WAIT_GE does NOT require the sensor
to stay above the threshold.

**Optional timeout**: WAIT_GE and WAIT_LE accept an optional third
argument: a timeout in seconds. If the condition is not met within
the timeout, the VM advances anyway. This prevents programs from
blocking forever if the machine cannot reach the target temperature.
If no timeout is specified, the wait is indefinite (backward compatible).
Brains writing new programs SHOULD pass a timeout on WAIT_GE / WAIT_LE
whenever the wait is "until the machine reaches a setpoint."

**Do not WAIT_GE / WAIT_LE the exact HOLD (or other regulation) target.**
HOLD uses a hysteresis band; the sensor may sit forever just below
the setpoint. Wait *inside* the band (below the HOLD target for
WAIT_GE, above it for WAIT_LE), and prefer an explicit timeout.

```
WAIT 600
WAIT_GE food 80               // wait forever until food >= 80
WAIT_GE food 93 1800          // wait up to 30 minutes for food >= 93
WAIT_LE chamber 50 600        // wait up to 10 minutes for chamber <= 50
WAIT_GE pressure 1.0 300      // wait up to 5 minutes for pressure >= 1.0
```

After a non-blocking HOLD (custom INST, §6), wait *inside* the band
with a timeout — never at the exact setpoint. Example 11.1:
`HOLD food 100` then `WAIT_GE food 90 1800`. `WAIT_GE food 100`
after `HOLD food 100` may never fire.

### 5.3 User Interaction

```
PROMPT <text>
```

Notify the user with the given text and **block the VM** until the
user acknowledges. The acknowledgment mechanism is machine-specific:

- BLE/app machines: brain sends `ACK` command over transport
- Touchscreen machines: user presses a button
- Voice machines: user says "OK" or "done"
- Factory machines: may auto-ACK after a configurable timeout

The spec defines only the **semantics** (notify + wait); each
machine implements the mechanism.

```
PROMPT add_culture_now
PROMPT flip_the_food
PROMPT check_doneness_and_confirm
```

Text must be underscore-safe (no spaces). The brain displays it
to the user with underscores converted to spaces.

**EMIT** is the non-blocking counterpart:

```
EMIT <text>
```

EMIT sends a notification and immediately advances to the next
instruction. Use EMIT for progress updates, PROMPT when the user
must act before continuing.

```
EMIT heating_started        # informational, program continues
PROMPT add_ingredients_now  # blocks until user acknowledges
```

### 5.4 Registers

Eight float registers `R0`–`R7` for arithmetic and loops.

```
SET_R <reg> <value>           # reg = value
ADD <reg> <value>             # reg += value
SUB <reg> <value>             # reg -= value
LOAD <reg> <sensor>           # reg = current reading of sensor
```

### 5.5 Flow Control

```
JMP <step>                    # Jump to step number
JGT <reg> <value> <step>      # Jump if reg > value
JLT <reg> <value> <step>      # Jump if reg < value
DJNZ <reg> <step>             # Decrement reg; jump if > 0
```

Step numbers are zero-indexed line numbers in the program.

**Turing-completeness:** registers + arithmetic + conditional jumps
= unbounded computation (limited by program memory).

**Infinite loop protection:** controllers MUST implement a maximum
jump count per execution tick (recommended: 10). If exceeded, the
controller pauses VM execution until the next tick.

### 5.6 Program Structure

```
LABEL <text>                  # Named marker (no runtime effect)
HALT                          # End program, all actuators off
```

LABEL is purely for readability — it does not affect execution.
HALT ends the program and forces all actuators off regardless of
any active custom instructions.

### 5.7 Disconnect Policy

```
DISCONNECT <policy>
```

Set what the controller does if communication with the brain is
lost during program execution.

```
DISCONNECT CONTINUE           # Keep running (default for SEQUENCE)
DISCONNECT PAUSE              # Pause, actuators off, wait for reconnect
DISCONNECT STOP               # All off, go idle
DISCONNECT ESTOP              # Emergency stop, hard latch
```

---

## 6. Custom Instructions

Everything beyond section 5 is machine-declared. The spec does not
define HOLD, CEILING, PRESSURIZE, or any other application-specific
instruction — those are declared by each machine in CAPABILITY.

### 6.1 Common Custom Instructions

While not required by the spec, most cooking machines will declare
these conventional instructions:

**HOLD** — temperature regulation:
```
INST HOLD args=sensor,value desc=regulate_heater_to_maintain_sensor_temperature
INST HOLD_OFF args=none desc=stop_temperature_regulation
```

**CEILING** — soft safety limit:
```
INST CEILING args=sensor,value desc=suppress_heater_if_sensor_exceeds_value
```

**BAND** — hysteresis configuration:
```
INST BAND args=value desc=set_hysteresis_band_for_regulation
```

Brains SHOULD recognize these conventional names when present but
MUST NOT assume they exist. Always check CAPABILITY.

### 6.2 Machine-Specific Custom Instructions

Machines can declare any custom instruction that matches their
capabilities:

```
INST PRESSURIZE args=value desc=lock_lid_heat_until_target_bar_reached
INST CIRCULATE args=none desc=start_circulation_pump_at_optimal_rate
INST WATCH_COLOR args=sensor,text desc=wait_until_camera_detects_color
INST FERMENT args=value,value desc=hold_temperature_for_hours
INST STEAM args=value desc=inject_steam_at_percentage
```

As long as the machine can implement them and describes them
clearly, an LLM can use them correctly.

### 6.3 Custom Instruction Semantics

When a custom instruction is executed:

1. **Blocking vs non-blocking:** by convention, custom instructions
   are non-blocking unless their description says "wait" or their
   name implies a blocking action. A brain that needs to wait should
   follow the custom instruction with an explicit `WAIT_GE` /
   `WAIT_LE` (with a timeout) or `PROMPT`.

   For temperature regulation (`HOLD` and equivalents): the follow-up
   wait MUST use a threshold *inside* the regulation band, not the
   HOLD setpoint itself, and SHOULD include a timeout. Example:
   `HOLD food 100` then `WAIT_GE food 90 1800`, never
   `WAIT_GE food 100`. See §5.2 and example 11.1.

2. **Actuator ownership:** a custom instruction may take exclusive
   control of certain actuators while active. If a program issues
   `SET <owned_actuator>` directly, the custom instruction yields
   control (see section 5.1 precedence rule).

3. **Termination:** custom instructions end when:
   - An explicit "off" instruction is issued (e.g., `HOLD_OFF`)
   - A `SET` on an owned actuator preempts them
   - `HALT`, `ESTOP`, or a FAULT occurs
   - The program ends

Machines SHOULD report custom instruction state transitions via
`EVENT` messages.

---

## 7. Telemetry

### 7.1 Status (periodic during active cooking)

```
STATUS mode=SEQUENCE pc=3 wait=1 ...machine-specific fields...
```

All STATUS lines MUST include these core fields first:

| Field | Type | Description |
|---|---|---|
| `mode` | string | Current controller mode |
| `pc` | int | Program counter (0-indexed) |
| `wait` | int (0/1) | 1 if VM is blocked on WAIT |
| `fault` | string | Fault reason or `NONE` |
| `up` | int | Uptime in seconds since boot |

**Dynamic fields** (names match CAPABILITY declarations):

| Field | Description |
|---|---|
| `<sensor>` | Current reading of each declared sensor |
| `<actuator>` | Current state of each declared actuator |

**Machine-specific fields** — the machine MAY include additional
fields related to its custom instructions (e.g., `hold_target=80`,
`hold_active=1`, `pressure_setpoint=1.2`). Brains should tolerate
unknown fields gracefully.

### 7.2 Events

```
EVENT <text>
```

Forwarded from EMIT instructions or generated by the controller for
state changes, fault clearings, custom instruction transitions, etc.

```
EVENT boiling
EVENT HOLD_STARTED
EVENT HOLD_RELEASED_BY_SET
EVENT LINK_LOST
```

### 7.3 Faults

```
FAULT <reason>
```

The controller has entered a fault state. All actuators are off.
The brain must send `CLEAR` to reset after investigating.

### 7.4 Prompts (blocking)

When the VM hits a `PROMPT` instruction, the controller sends:

```
PROMPT <text>
```

The brain MUST respond with:

```
ACK
```

...to release the VM. Until ACK is received, the VM remains blocked
at the PROMPT. Status broadcasts continue normally with `wait=1`.

---

## 8. Controller Commands (non-program)

These are sent by the brain outside of program execution.

```
PING                          → PONG
STATUS                        → full STATUS line
CAPABILITY                    → capability declaration block
ACK                           → acknowledge a PROMPT, release VM

# Direct actuator control (requires DIRECT mode)
MODE DIRECT
SET heater 1
HEARTBEAT                     → required periodically in DIRECT mode

# Program management
PROGRAM CLEAR
PROGRAM ADD <instruction>
PROGRAM RUN
PROGRAM STOP
PROGRAM PAUSE
PROGRAM RESUME
PROGRAM NEXT                  # Skip current WAIT or PROMPT
PROGRAM LIST

# Safety
ESTOP
CLEAR                         # Clear fault → idle

# Configuration
CONFIG
CONFIG SET <key> <value>
CONFIG SAVE
CONFIG DEFAULTS

# Sensor calibration (if FEATURES includes calibration)
CAL START <sensor>
CAL CAPTURE <sensor> <reference>
CAL COMPUTE <sensor>
CAL RESULT <sensor>
CAL APPLY <sensor>
CAL ABORT

# Auto-tune (if FEATURES includes autotune)
TUNE START
TUNE ABORT
TUNE STATUS
TUNE RESULT
```

---

## 9. Controller Modes

```
IDLE       All actuators off. Waiting for commands.
DIRECT     Brain controls actuators directly. Heartbeat required.
SEQUENCE   Executing a loaded CookVM program.
PAUSED     Program paused, actuators off, timers frozen.
CALIBRATE  Sensor calibration session in progress.
TUNING     Auto-tune step-response test in progress.
FAULT      Safety violation. Must CLEAR.
ESTOP      Emergency stop. Hard latch. Must CLEAR.
```

---

## 10. Safety Requirements

Every compliant controller MUST implement:

1. **Hard sensor limits** — declared in LIMIT, cannot be overridden.
   Exceeding a limit triggers FAULT.

2. **Sensor validation** — open/short circuit detection within 5
   seconds triggers FAULT.

3. **Heartbeat timeout** — DIRECT mode requires periodic HEARTBEAT;
   default timeout 30s.

4. **Disconnect policy** — default CONTINUE for SEQUENCE, ESTOP for
   DIRECT.

5. **Infinite loop protection** — max 10 jumps per tick.

6. **Watchdog timer** — hardware watchdog required.

7. **Power-on state** — all actuators off on boot.

8. **Message buffer** — STATUS must support at least 256 bytes.

9. **Custom instruction safety** — custom instructions MUST respect
   LIMIT hard limits. A HOLD or PRESSURIZE that would exceed a
   declared limit must refuse to start or halt gracefully.

10. **PROMPT timeout** — machines SHOULD implement a configurable
    PROMPT timeout (recommended default: 30 minutes) to prevent
    indefinite blocking if the user disappears.

---

## 11. Example Programs

Examples set soft limits (`CEILING`) before any heating instruction.
Brains SHOULD do the same, and SHOULD set an explicit `DISCONNECT`
policy at the top of any program that heats unattended.

### 11.1 Boiled Eggs (bread machine)

Uses only core instructions plus the machine's declared HOLD and
CEILING custom instructions.

```
CEILING chamber 120
HOLD food 100
WAIT_GE food 90 1800
EMIT boiling
WAIT 720
HOLD_OFF
SET fan 1
WAIT 300
SET fan 0
EMIT ready
HALT
```

`HOLD food 100` then `WAIT_GE food 90 1800` — the wait threshold is
below the hold (boil detect / inside the band) and the timeout stops
an unreachable wait from hanging the VM. Do not write
`WAIT_GE food 100` after `HOLD food 100`.

### 11.2 Yogurt (bread machine) with User Interaction

```
CEILING chamber 120
HOLD food 82
WAIT_GE food 80 1800
EMIT pasteurized
HOLD_OFF
SET fan 1
WAIT_LE food 44 1800
SET fan 0
PROMPT add_yogurt_culture_now
SET motor 1
WAIT 30
SET motor 0
HOLD food 43
WAIT 28800
HOLD_OFF
PROMPT yogurt_ready_refrigerate_now
HALT
```

Note how `PROMPT add_yogurt_culture_now` blocks the VM until the
user confirms they've added the culture before the motor starts
stirring. This was impossible in v1.1 with just `EMIT`.

### 11.3 Pressure Cooker Stew

Uses the pressure cooker's custom instructions `PRESSURIZE` and
`DEPRESSURIZE`.

```
PROMPT add_ingredients_and_close_lid
PRESSURIZE 1.0
EMIT pressure_reached
WAIT 2400
DEPRESSURIZE
PROMPT safe_to_open_enjoy
HALT
```

The program doesn't need to know how pressurization works — it just
calls the instruction the machine declared.

### 11.4 Stepped hold (registers count slices, HOLD takes literals)

`HOLD` operands are numeric literals declared by the machine's INST
(`sensor`, `value`). There is no `SET_REG food_target` unless the
machine declares that INST. To raise a setpoint, emit a new `HOLD`
with the next literal. Registers are for counting slices, not for
inventing opcodes.

```
CEILING chamber 120
HOLD food 40
WAIT_GE food 38 600
SET_R R0 6
LABEL slice
WAIT 300
EMIT slice_done
DJNZ R0 4
HOLD food 50
WAIT_GE food 48 600
WAIT 300
HOLD_OFF
EMIT ramp_complete
HALT
```

`DJNZ` / `JMP` take **zero-indexed line numbers**, not LABEL names.
LABEL is a comment for humans. Inserting a line above the loop
changes the DJNZ target.

---

## 12. Compliance Levels

### Level 1 — Minimal

Core instructions: SET, WAIT, WAIT_GE, WAIT_LE, EMIT, HALT, LABEL.
CAPABILITY declaration with at least ACTUATOR, SENSOR, LIMIT.
Commands: PING, STATUS, CAPABILITY, ESTOP, CLEAR.

### Level 2 — Standard

Level 1 plus: PROMPT (with ACK handling), registers (SET_R, ADD,
SUB, LOAD), flow control (JMP, JGT, JLT, DJNZ), DISCONNECT,
PROGRAM management, CONFIG, at least one custom instruction for
temperature regulation (typically HOLD).

### Level 3 — Extended

Level 2 plus: proportional actuators, multiple custom instructions,
SET_REG, sensor calibration (CAL), auto-tune (TUNE), actuator
verification (VERIFY).

---

## 13. Migration from v1.1

For controllers and brains upgrading from CookVM v1.1:

### Brain changes

- Stop hardcoding TARGET, CONTROL, HOLD in prompts
- Read CAPABILITY on connect, build programs from declared INST
- Handle `PROMPT` ↔ `ACK` for blocking user interaction
- Recognize custom instruction names from CAPABILITY, not from spec

### Controller changes

- Emit `INST` lines in CAPABILITY for every custom instruction
- Replace fixed TARGET/CONTROL with declared HOLD (or whatever name
  fits the machine)
- Implement PROMPT as a blocking primitive with ACK handling
- Update header to `COOKVM 2.0`

### Backward compatibility

- v1.1 brains can still work with v2.0 controllers that declare
  `INST HOLD args=sensor,value` — HOLD behaves like v1.1 TARGET
- v2.0 brains querying a v1.1 controller should fall back to the
  fixed instruction set

---

## 14. Reference Card

```
CORE INSTRUCTIONS (v2.0 universal)
  SET <actuator> <value>       SET_R <reg> <value>
  SET_REG <actuator> <reg>     ADD <reg> <value>
  WAIT <seconds>               SUB <reg> <value>
  WAIT_GE <sensor> <value> [timeout_s]
  WAIT_LE <sensor> <value> [timeout_s]
  EMIT <text>                  LOAD <reg> <sensor>
  PROMPT <text>                JMP <step>
  LABEL <text>                 JGT <reg> <value> <step>
  HALT                         JLT <reg> <value> <step>
  DISCONNECT <policy>          DJNZ <reg> <step>

CUSTOM INSTRUCTIONS (machine-declared via INST)
  Anything the machine declares in its CAPABILITY block.
  Read CAPABILITY to learn them. Examples:
    HOLD, HOLD_OFF, CEILING, BAND, PRESSURIZE, CIRCULATE, ...
  PROMPT is core (§5.3), not an INST.

KEY RULES
  This spec plus the machine's CAPABILITY are both required to program it.
  Core instructions work on every CookVM 2.0 machine.
  Custom instructions are declared with plain-English descriptions.
  SET on an actuator takes control (last-write-wins).
  PROMPT blocks the VM until ACK is received.
  Programs MUST end with HALT.
  Use only names declared in CAPABILITY.
  After HOLD <sensor> <T>, wait inside the band with a timeout:
    RIGHT: HOLD food 100 → WAIT_GE food 90 1800
    WRONG: HOLD food 100 → WAIT_GE food 100
```

---

*CookVM is an open specification. Use it, extend it, build machines
with it. Licensed under the Apache License 2.0 (see `LICENSE`).*
