# CookVM

**An open text protocol and tiny virtual machine for cooking appliances.**

CookVM separates *what to cook* (a short program) from *how the machine works* (the
controller). A brain (an app, a script or an AI agent) asks the appliance what it has
(`CAPABILITY`), writes a program from the core instructions plus the machine's declared
custom instructions, uploads it line by line, and watches `STATUS` telemetry. The
controller enforces its own safety limits and does not care what food is in the pan.

```
PING                      → PONG
CAPABILITY                → COOKVM 2.0 Example_BreadMachine / ACTUATOR … / SENSOR … / INST HOLD … / END_CAPABILITY
PROGRAM CLEAR
PROGRAM ADD CEILING chamber 120
PROGRAM ADD HOLD food 100
PROGRAM ADD WAIT_GE food 90 1800
PROGRAM ADD WAIT 600
PROGRAM ADD HOLD_OFF
PROGRAM ADD HALT
PROGRAM RUN               → OK PROGRAM_RUN 6
STATUS                    → STATUS mode=SEQUENCE pc=2 wait=1 fault=NONE up=95 chamber=88.1 food=61.4 heater=1 …
```

## Why
- **One language for many appliances.** The same yogurt program runs on a bread machine,
  a rice cooker or a multicooker. Each machine maps it to its own hardware.
- **Self-describing machines.** The CAPABILITY block names the sensors, actuators, limits,
  custom instructions and quirks (`NOTES`), so a brain needs only the spec plus that block.
- **Microcontroller-sized.** Line-based text, a fixed instruction set, 8 registers,
  128-step programs, and no dynamic allocation in the C core.
- **Safe by default.** Hard limits, sensor validation, a watchdog, a heartbeat, disconnect
  policies and latched faults all live in the controller, not the brain.
- **LLM-friendly.** It is plain text with a small grammar, and an emulator lets an agent
  dry-run a program before it touches a real heater.

## Repository layout

| Path | Contents |
|---|---|
| `spec/CookVM_Spec_v2_0.md` | the specification (v2.0 draft) |
| `spec/CHANGELOG.md` | v1.1 → v2.0 changes and open issues |
| `reference/python/` | `cookvm` Python package: CAPABILITY/STATUS parsing, program validation, emulator |
| `firmware/libcvm/` | portable C99 controller core (`cvm.c`, `cvm.h`, `cvm_hal.h`) |
| `docs/PORTING.md` | step-by-step appliance retrofit guide, including field safety lessons |
| `examples/` | sample CAPABILITY blocks and programs |

## Quick start (no hardware)

```bash
cd reference/python
python -m unittest discover -s tests -v      # stdlib only; runs sample programs through the emulator
```

```python
# from the repository root, with reference/python/src on PYTHONPATH (or `pip install reference/python`)
from cookvm import Capability, validate_ops, emulate
cap = Capability.from_lines(open("examples/capabilities/bread_machine.cap").read().splitlines())
ops = [l for l in open("examples/programs/boiled_eggs.cvm").read().splitlines()
       if l.strip() and not l.startswith("#")]
print(validate_ops(ops, cap))                 # [] = valid
print(emulate(ops, cap, food_params={"liquid_ml": 1000, "food_type": "eggs_in_water"}).report())
```

## Talking to a real machine
1. Connect over serial, BLE Nordic UART or TCP. Send `PING` and expect `PONG`.
2. Send `CAPABILITY`. Use only the names it declares, and read its `NOTES`.
3. Send `STATUS`. The fields are `mode pc wait fault up`, then each sensor and actuator by
   name, then machine-specific fields such as `hold_active` and `hold_target`.
4. `PROGRAM CLEAR`, then one `PROGRAM ADD <instr>` per line (each reply is `OK [i] …`),
   then `PROGRAM RUN`.
5. Watch STATUS and EVENTs. Answer `PROMPT <text>` with `ACK`. Stop with `PROGRAM STOP`,
   or `ESTOP` in an emergency. **After any stop, confirm with STATUS that the heater
   reads 0.**

## Porting to a new appliance
Read [`docs/PORTING.md`](docs/PORTING.md). In short: survey the loads and sensors, wire
relays or SSRs and NTC probes, implement `cvm_hal.h`, add an independent hard-limit check,
write the CAPABILITY block, pick a transport, test in the emulator, then on the bench,
then with water.

## Status and maturity
**Experimental. The spec is a draft.** CookVM 2.0 has run real cooks on one retrofitted
bread machine (dual-core microcontroller over BLE). A translator for a commercial
pressure cooker was also prototyped privately; it is not included here. Expect breaking
changes before 2.1. The reference firmware core has known gaps against the spec, listed
in `firmware/libcvm/README.md` and `spec/CHANGELOG.md` → "Open issues". Read them, and
the field lessons in `docs/PORTING.md`, before you power a heater. Nothing here is
certified for safety. Use at your own risk.

## License
Apache License 2.0. See [`LICENSE`](LICENSE) and [`NOTICE`](NOTICE).
Copyright 2026 the CookVM authors.

## Contributing
See [`CONTRIBUTING.md`](CONTRIBUTING.md).
