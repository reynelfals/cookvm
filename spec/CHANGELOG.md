# CookVM specification changelog

## v2.0 (draft, April 2026; editorial clarifications September–October 2026)

The core idea behind v2.0: **the machine documents how to program it.** The spec keeps
only universal primitives. Machine-specific behaviour is declared in `CAPABILITY`.

### Added
- **`INST` lines in CAPABILITY** (§4.6). Machines declare their own instructions
  (`INST <NAME> args=<types> desc=<text>`). Standard arg types: `sensor`, `actuator`,
  `value`, `text`, `reg`, `step`.
- **`NOTES` lines in CAPABILITY** (§4.7). Machine quirks and calibration hints, ideally
  updated by the machine over time.
- **`PROMPT <text>`** as a core blocking instruction (§5.3), released by the brain's **`ACK`**
  command (§7.4). Recommended configurable PROMPT timeout (safety rule 10).
- **Optional timeout on `WAIT_GE` / `WAIT_LE`**: `WAIT_GE <sensor> <value> [timeout_s]`
  (§5.2). On timeout the VM advances. Brains SHOULD always pass one for "reach setpoint" waits.
- **Wait-inside-the-band rule** (§5.2, §6.3): after `HOLD <sensor> <T>`, wait at a threshold
  inside the regulation band, never at exactly `T`.
- **SET precedence rule** (§5.1): `SET` on an actuator owned by a custom instruction is
  last-write-wins and releases it (`EVENT HOLD_RELEASED_BY_SET`).
- **Custom-instruction semantics** (§6.3): non-blocking by default, actuator ownership,
  termination conditions.
- STATUS core field **`fault`** and **`up`** are now required up front; everything else is
  dynamic and named after CAPABILITY declarations (§7.1).
- `PROGRAM NEXT` now also skips a pending `PROMPT`.
- BLE pacing guidance: ~20 ms between multi-line responses (§3).
- Safety rule 9: custom instructions must respect hard `LIMIT`s.
- Explicit statement that programming a machine needs **this spec plus its CAPABILITY**.
- New sensor types `voltage`, `current` and units `V`, `A`.

### Changed
- **`TARGET`, `TARGET_REG`, `CONTROL`, `CEILING`, `BAND` removed from the core ISA.**
  Regulation is now a machine-declared custom instruction, conventionally
  `HOLD <sensor> <value>` / `HOLD_OFF`, with `CEILING <sensor> <value>` and `BAND <value>`
  as conventional (not required) custom instructions (§6.1).
- **`HOLD` is no longer a controller mode.** Modes are IDLE, DIRECT, SEQUENCE, PAUSED,
  CALIBRATE, TUNING, FAULT, ESTOP.
- STATUS fields `tgt`, `duty`, `ceil`, `band`, `sensor`, `ceilHit` are no longer standard;
  machines MAY report them as machine-specific fields (e.g. `hold_active`, `hold_target`).
- CAPABILITY header is `COOKVM 2.0 <machine_name>`; `desc` values are required single tokens.
- Compliance levels re-cut: Level 1 no longer needs regulation; Level 2 adds PROMPT,
  registers, flow control, DISCONNECT, PROGRAM, CONFIG and at least one regulation INST.

### Removed
- The `CONTROL type=... cycle_ms=...` CAPABILITY line (brains should ignore it if seen).
- The out-of-band JSON **Machine Profile** (v1.1 §10). Its content now lives in
  CAPABILITY (`VOLUME`, `POWER`, `NOTES`).
- The detailed calibration and auto-tune procedures (v1.1 §14) are no longer normative
  text. `CAL …`, `TUNE …` remain as controller commands gated by `FEATURES`. `VERIFY`
  appears only in the Level 3 list (no command syntax is given in v2.0; see "Open issues").

### Editorial changes in this published copy
- Example machine names made generic (`Example_BreadMachine`, `Example_PressureCooker`);
  a brand-name appliance mention replaced with "multicooker".
- `INST PRESSURIZE args=bar` corrected to `args=value` (standard arg type).
- Examples now set `CEILING` before `HOLD`; added a note recommending ceilings and an
  explicit `DISCONNECT` policy first. Jump targets in §11.4 are unchanged.
- License line updated to Apache-2.0.

### Open issues (to resolve in v2.1)
- `VERIFY` is listed in Level 3 but its syntax was dropped from §8.
- §8 lists `CONFIG SET`, `CONFIG DEFAULTS`, `CAL …`; the reference firmware does not
  implement them yet.
- No standard response grammar for `PROGRAM LIST` or `PROGRAM ADD` (the reference firmware
  replies `OK [<index>] <instr>` and lists opcode names only).
- §7.3 says the controller sends `FAULT <reason>`; the reference core only reports the
  fault in STATUS (`fault=`).
- No guidance yet on concurrent high-draw loads; see the field lessons in `docs/PORTING.md`.
- `PROGRAM STOP`, `PAUSE` and `MODE IDLE` should be specified to zero reported actuator
  state (see firmware known issues).

## v1.1 (April 2026)
Initial public draft: fixed ISA with `CONTROL`, `TARGET`, `CEILING`, `BAND`, `SET`,
waits, registers, flow control, `EMIT`, `DISCONNECT`; HOLD mode; JSON machine profile;
calibration, auto-tune and actuator verification procedures.
