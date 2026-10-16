# Porting CookVM to an appliance

This guide covers retrofitting an existing appliance (bread machine, rice cooker, slow
cooker, multicooker, pressure cooker, sous-vide bath, and so on) with a CookVM controller.
At the end, any CookVM brain (an app, a script, or an AI agent) can discover the machine
and run programs on it.

> **Mains voltage can kill, and heaters cause fires.** Retrofit only if you are competent
> with mains wiring. Keep the appliance's original thermal fuse and cutouts in circuit.
> Never leave a prototype heating unattended. CookVM's software safety layer adds to the
> appliance's hardware protection. It never replaces it.

## 0. Overview

```
brain ──text lines──► transport ──► controller (libcvm + your HAL) ──► relays/SSRs/drivers
      ◄─STATUS/EVENT──           ◄── sensors (NTC, thermocouple, pressure, load cell)
```

You write three things:
1. A **HAL** (`cvm_hal.h`) for your board: pins, sensor maths, storage, transport.
2. A **machine wrapper** that declares actuators and sensors, adds hard limits and an
   independent over-temperature check, and answers `CAPABILITY` with a full block.
3. A **CAPABILITY block** that tells brains everything they need to program the machine.

## 1. Survey the appliance

- List every load: heater element(s) with wattage, motor (paddle, stirrer, pump), fan,
  valves, lid lock, and so on. Note the supply circuit and any built-in protection.
- Find where heat is sensed today. Most appliances have an NTC thermistor on the wall or
  base. Measure its resistance at room temperature and in boiling water.
- Decide which loads may run **at the same time**. Many appliances are designed never to
  run heater and motor together. Their supply, triac or protection circuit may trip if you
  do (see Field lessons).
- Keep the original thermal fuse/TCO in series with the heater.

## 2. Sensors

- **Temperature.** Read an NTC through a divider into the ADC. Average several samples,
  convert with the Beta or Steinhart–Hart equation, and calibrate against a reference
  thermometer at about 0 °C and about 100 °C. Thermocouples or RTDs need an amplifier
  (MAX31855/31865-class).
- Typical layout: a **chamber/wall** sensor near the element (fast, for safety ceilings)
  and a **food/process** probe immersed in the food (slow, for doneness).
- **Validity.** Treat out-of-range ADC values (open or short) as invalid. libcvm faults
  (`SENSOR_<name>`) after `sensor_fault_ms` (5 s) of invalid readings.
- Return values to libcvm in milli-units (m°C, mbar, mg). Return `CVM_SENSOR_INVALID`
  when a reading is bad.
- Sensor names are what programs use (`food`, `chamber`, `pressure`). Keep them short
  (11 characters or less for the reference core).

## 3. Actuators

- Switch mains loads with properly rated relays or zero-cross SSRs, with snubbers on
  inductive loads (motors). Use opto-isolated driver boards and fuse each load.
- `binary` actuators are 0/1. `proportional` actuators declare a range (for example
  `range=0-100 unit=%`) and need a PWM, phase-angle or time-proportioning driver.
- **All outputs must be OFF at boot** (set pins LOW before anything else), and
  `cvm_hal_all_off()` must turn off every load.
- Pick one actuator as the **heat actuator** (`cvm_set_heat_actuator`). HOLD and CEILING
  act on it.

## 4. Safety layer (mandatory)

Put the following in the controller. Never leave it to the brain:

1. **Hard limits** per sensor (`LIMIT chamber_max=... food_max=...`). Check them on the
   real-time core every tick, *independently* of the VM. Exceeding one gives ESTOP/FAULT
   with all outputs off.
2. **Sensor validation** (open/short) leading to FAULT.
3. **Hardware watchdog** fed from the control loop (the reference port uses 8 s).
4. **Heartbeat** in DIRECT mode (default 30 s). Enforce it for *every* actuator, not just
   the heater.
5. **Disconnect policy.** In DIRECT mode a disconnect means ESTOP. In SEQUENCE use the
   program's `DISCONNECT` policy.
6. **Mutual exclusion for high-draw loads** if your supply or protection can't handle
   them together. Enforce it in firmware (refuse or serialise) and declare it in
   `NOTES`.
7. **FAULT/ESTOP latch** until an explicit `CLEAR`. Make sure `CLEAR` does nothing if the
   cause is still present.
8. **No test backdoors in shipping firmware.** Simulated-sensor ("bench") modes,
   auto-tune and similar tools must never clear faults, bypass hard limits or drive real
   loads. Compile them out of production builds.
9. **Reported state must match physical state.** Every path that switches outputs off
   (stop, pause, idle, disconnect) must also update the reported actuator values.

## 5. Firmware integration (libcvm)

```c
g_heat = cvm_add_actuator(&cvm, "heater", CVM_ACT_BINARY, 0, 1);
g_fan  = cvm_add_actuator(&cvm, "fan",    CVM_ACT_BINARY, 0, 1);
g_ch   = cvm_add_sensor(&cvm, "chamber", CVM_SENS_TEMPERATURE);
g_food = cvm_add_sensor(&cvm, "food",    CVM_SENS_TEMPERATURE);
cvm_set_heat_actuator(&cvm, g_heat);
cvm_set_control_sensor(&cvm, g_food);
cvm_init(&cvm);
// control loop, every 200 ms:  hard-limit check → cvm_tick(&cvm)
// on each received line:        if CAPABILITY → send your block, else cvm_handle_command()
// ~1 Hz while not IDLE:         cvm_broadcast_status(&cvm)
```

A dual-core MCU works well: transport and parser on one core; sensors, hard limits and
`cvm_tick` on the other. Protect shared state, and read `firmware/libcvm/README.md` for
known issues before you ship.

## 6. The CAPABILITY file

The CAPABILITY block is the machine's programming manual. Brains read it on every
connect. Example (`examples/capabilities/bread_machine.cap`):

```
COOKVM 2.0 Example_BreadMachine
ACTUATOR heater type=binary range=0-1 desc=main_resistive_heater
ACTUATOR fan type=binary range=0-1 desc=air_circulation_fan
ACTUATOR motor type=binary range=0-1 desc=bread_kneading_paddle
SENSOR chamber type=temperature unit=C desc=wall_near_heater_element
SENSOR food type=temperature unit=C desc=immersed_process_sensor_on_spindle
LIMIT chamber_max=160 food_max=120
VOLUME pan_ml=3000 working_ml=2200
POWER heater_w=750
INST HOLD args=sensor,value desc=regulate_heater_to_reach_and_maintain_sensor_temperature
INST HOLD_OFF args=none desc=stop_temperature_regulation
INST CEILING args=sensor,value desc=suppress_heater_if_sensor_exceeds_value
INST BAND args=value desc=set_hysteresis_band_for_regulation
NOTES boiling_peaks_at_96C_on_food_sensor
NOTES heater_and_motor_must_not_run_at_the_same_time
FEATURES autotune disconnect_policy
END_CAPABILITY
```

Checklist:
- `desc` fields are semantic and underscore-joined. Brains use them to tell the heater,
  mixer, process sensor and so on apart.
- Declare **only** the INSTs you actually implement, with accurate `args`.
- Use `NOTES` for anything a cook needs to know: where boiling peaks on your probe,
  thermal lag and coast, loads that can't run together, "no physical button for PROMPT",
  and the like.
- Pace multi-line replies (about 20 ms per line) on BLE.
- Keep a single source of truth. If a brain caches the block in a file, regenerate it
  from the device.

## 7. Transports

All transports carry the same UTF-8 lines (256 bytes max, `\n`-terminated).

| Transport | Notes |
|---|---|
| **USB serial** | 115200 baud, simplest for bring-up. Keep it enabled as a maintenance port. |
| **BLE (Nordic UART Service)** | Service `6E400001-B5A3-F393-E0A9-E50E24DCCA9E`, RX (write) `…0002`, TX (notify) `…0003`. Negotiate a large MTU. Put `mode pc wait` first in STATUS. Pace notifications. Expect missed responses (see Field lessons). |
| **Wi-Fi (TCP / MQTT / HTTP)** | One line per message. **Require authentication** and never expose an unauthenticated control port to a network: anyone who can send `MODE DIRECT` + `SET heater 1` can heat your appliance. |

On connect, send a greeting such as `COOKVM 2.0 <machine> mode=<MODE>`.

## 8. Test with the emulator, then on the bench, then with water

1. **Emulator.** Put your CAPABILITY in a `.cap` file and run programs through
   `reference/python` (`emulate(ops, cap)`). Fix every `error` and review warnings.
2. **Host build.** Compile libcvm against a stub HAL on your desktop and script command
   sequences (PING, CAPABILITY, PROGRAM ADD/RUN/STOP, STATUS) to check responses.
3. **Bench, loads disconnected.** Check each output with a meter or LED. Check that
   faults latch, ESTOP works, and the watchdog resets with all outputs off.
4. **Water test.** Put about 1 L of water in the pan with the probe immersed. Run a HOLD
   at 60 °C, then a boil. Log STATUS, measure overshoot and coast, and write them into
   `NOTES`.
5. **Stop/abort drills.** After `PROGRAM STOP`, `PAUSE`, a disconnect and `ESTOP`, check
   that STATUS reports every actuator at 0 *and* that the loads are physically off.

## 9. Field lessons (safety)

These come from real runs on a retrofitted bread machine. Treat them as requirements.

1. **Concurrent high-draw loads can take down the controller.** On some hardware, running
   the heater and motor together tripped an external protection circuit. That cut power
   to the controller and dropped BLE mid-cook. Never run high-draw loads at the same time
   unless the CAPABILITY says it is safe. Enforce the rule in firmware and declare it in
   `NOTES`.
2. **A stop is not proof the heater is off.** After a program stop, some firmware still
   reported `heater=1` in IDLE, and `SET heater 0` outside a program was rejected
   (`ERR NOT_DIRECT`). The fix was a tiny program: `HOLD_OFF`, `SET heater 0`, `HALT`.
   Always confirm `heater=0` with STATUS after any stop. Make your firmware's stop paths
   zero both the outputs and the reported state.
3. **Thermal carryover.** After heating stopped, the food probe kept rising by about 4 °C.
   For cakes and other probe-terminated cooks, stop around 94–96 °C food temperature.
   Measure your machine's coast and put it in `NOTES`.
4. **Use the raw protocol for stops.** One host app's own "stop" wrapper sent a bare
   `STOP`, which the firmware rejected. Brains should send the protocol commands
   (`PROGRAM STOP`, `ESTOP`) and check the reply. Firmware may choose to accept `STOP` as
   an alias.
5. **"No response" doesn't mean "not applied".** A BLE transport can report a timeout
   even though the command was executed. Re-read STATUS or `PROGRAM LIST` before you
   retry anything that has side effects.
6. **PROMPT needs a way to ACK.** PROMPT blocks until `ACK`. On a machine with no
   physical button, and no app path that sends ACK, a PROMPT can hang the program while
   the heater keeps running. Leave PROMPT out there, or implement the PROMPT timeout.
7. **Do not let test modes override faults.** Simulated-sensor, tune or clear commands
   must never be used to push past a FAULT. Find and fix the cause first.
