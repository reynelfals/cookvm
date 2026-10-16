# libcvm — portable C99 CookVM controller core

`cvm.c` / `cvm.h` / `cvm_hal.h` implement the controller side of CookVM 2.0 in pure C99
with no dynamic allocation. They have been built and run on an RP2040/RP2350-class
microcontroller (Arduino core), and compile cleanly on a desktop with
`gcc -std=c99 -Wall -Wextra`.

## Using it
1. Implement every function in `cvm_hal.h` for your board (time, actuators, sensors,
   persistent storage, transport send, watchdog, all-off).
2. Declare actuators/sensors with `cvm_add_actuator` / `cvm_add_sensor`, then call
   `cvm_set_heat_actuator`, `cvm_set_control_sensor`, `cvm_init`.
3. Call `cvm_tick()` every `CVM_TICK_MS` (200 ms) from a real-time loop.
4. Feed each received text line to `cvm_handle_command()`.
5. Call `cvm_on_connect()` / `cvm_on_disconnect()` from your transport.
6. Broadcast `cvm_broadcast_status()` about once per second while not IDLE.
7. Override the generic `CAPABILITY` reply in your machine wrapper. It should send
   your machine name, `desc=` fields, `LIMIT`, `VOLUME`, `POWER`, `NOTES` and `FEATURES`.
   Intercept the `CAPABILITY` command before passing lines to `cvm_handle_command`.

See `docs/PORTING.md` for the full retrofit guide.

## Implemented
Program opcodes: NOP, SET, SET_REG, WAIT, WAIT_GE/WAIT_LE (optional timeout, emits
`EVENT TIMEOUT_WAIT_GE|LE`), SET_R, LOAD, ADD, SUB, JMP, JGT, JLT, DJNZ, EMIT, PROMPT,
LABEL, DISCONNECT, HALT, plus custom HOLD, HOLD_OFF, CEILING, BAND. Max 128 steps.
Commands: PING, STATUS/`?`, CAPABILITY (generic), MODE, SET (DIRECT only), HEARTBEAT/HB,
ACK, HOLD, HOLD_OFF, CEILING, BAND, DISCONNECT, PAUSE, RESUME,
PROGRAM CLEAR|ADD|RUN|STOP|NEXT|PAUSE|RESUME|LIST, ESTOP, CLEAR, CONFIG, CONFIG SAVE.

## Known issues (fix before relying on them)
- **Stale actuator telemetry after stop.** `PROGRAM STOP`, `PAUSE`, `MODE IDLE` and the
  STOP/PAUSE disconnect policies call `cvm_hal_all_off()` but do not zero
  `actuators[i].current`. STATUS can keep reporting `heater=1` (and `wait=1`) in IDLE.
  `HALT`, `ESTOP` and FAULT do zero it. Workaround: run `HOLD_OFF / SET heater 0 / HALT`.
  Fix: zero `current` (and `vm_waiting`) wherever `cvm_hal_all_off()` is called.
- **Bare `STOP` is rejected** (`ERR UNKNOWN`). Only `PROGRAM STOP` and `ESTOP` exist.
- **`SET` outside DIRECT mode returns `ERR NOT_DIRECT`**, even in IDLE.
- **Direct `SET` does not range-check.** The spec says out-of-range values get `ERR`.
  Program `SET` clamps silently.
- **`BAND` is stored but unused.** The heater loop is time-proportioning
  (`prop_band`, `anticipation_ms`, `cycle_ms`). It is not hysteresis.
- **`HOLD` auto-sets a ceiling** of target + 60 °C on sensor 0 if none is set.
- **The generic CAPABILITY lists `INST PROMPT`**, but the spec makes PROMPT a core
  instruction. It also omits the machine name and `desc=`.
- **FAULT is not announced** with a `FAULT <reason>` line, only in STATUS `fault=`.
- **The single-slot event buffer** means two events in the same tick (for example
  `HOLD_STARTED` followed by `EMIT x`) can overwrite each other. Events are also dropped
  while disconnected.
- **The DIRECT-mode heartbeat** is only enforced while the heater is on.
- **`MODE SEQUENCE|PAUSED|TUNING|CALIBRATE`** can be set directly without a program.
- **`PROGRAM LIST` prints opcode names only** (no arguments).
- **Long tokens get split.** The tokenizer cuts every token at 11 characters
  (`CVM_NAME_LEN` - 1) and turns the remainder into the *next* token. So
  `PROGRAM ADD PROMPT add_yogurt_culture_now` is stored as `PROMPT add_yogurt_`.
  This affects EMIT, PROMPT and LABEL text, and any sensor or actuator name over 11
  characters. Keep these at 11 characters or less, or raise `CVM_NAME_LEN`. A proper fix
  copies the free-text argument straight from the line.
- **Weak argument checking in `PROGRAM ADD`.** An unknown `DISCONNECT` policy is accepted
  as CONTINUE. Missing operands (e.g. `SET heater` with no value) are accepted and read
  an uninitialised token buffer. Always send complete instructions and check the echoed
  `OK [i] ...` text.
- **Not implemented:** PROMPT timeout, `CONFIG SET`, `CONFIG DEFAULTS`, `CAL`, `VERIFY`.
- **No locking.** On dual-core targets, `cvm_handle_command` (transport core) and
  `cvm_tick` (control core) touch the same state. Serialise them with a mutex or queue,
  and only call `cvm_hal_send` from a context where your transport allows it.
