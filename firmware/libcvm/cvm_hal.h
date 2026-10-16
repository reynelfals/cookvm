/*
 * CVM — Cooking Virtual Machine
 * Hardware Abstraction Layer (HAL)
 *
 * Implement these functions for your specific hardware.
 * The CVM core calls them — it never touches hardware directly.
 *
 * SPDX-License-Identifier: Apache-2.0
 * Copyright 2026 the CookVM authors
 */

#ifndef CVM_HAL_H
#define CVM_HAL_H

#include <stdint.h>
#include <stdbool.h>

#ifdef __cplusplus
extern "C" {
#endif

/*
 * ── TIME ──
 * Return monotonic milliseconds since boot.
 * Must not wrap more than once per 49 days (uint32_t).
 */
uint32_t cvm_hal_millis(void);

/*
 * ── ACTUATORS ──
 * Set an actuator by index. Value meaning depends on type:
 *   Binary:        0 = off, non-zero = on
 *   Proportional:  0–10000 (0.00%–100.00%, fixed-point)
 *
 * index: 0-based actuator index (as declared in capability)
 * value: raw integer value
 */
void cvm_hal_set_actuator(uint8_t index, int32_t value);

/*
 * ── SENSORS ──
 * Read a sensor by index. Return value in millidegrees (°C × 1000),
 * millibars, milligrams, etc. depending on sensor type.
 * Return CVM_SENSOR_INVALID if the sensor is faulty.
 *
 * index: 0-based sensor index (as declared in capability)
 */
#define CVM_SENSOR_INVALID INT32_MIN

int32_t cvm_hal_read_sensor(uint8_t index);

/*
 * ── SENSOR VALIDITY ──
 * Return true if the sensor at index is currently giving valid readings.
 */
bool cvm_hal_sensor_valid(uint8_t index);

/*
 * ── PERSISTENT STORAGE ──
 * Save/load a block of bytes to non-volatile storage.
 * Used for calibration constants and tuning parameters.
 * Return true on success.
 */
bool cvm_hal_config_save(const void* data, uint16_t len);
bool cvm_hal_config_load(void* data, uint16_t len);

/*
 * ── TRANSPORT (send message to brain) ──
 * Send a null-terminated string to the connected brain.
 * The HAL handles the transport (BLE, Serial, TCP, etc.)
 * Return true if sent successfully.
 */
bool cvm_hal_send(const char* message);

/*
 * ── WATCHDOG ──
 * Feed the hardware watchdog timer.
 * Called once per control tick.
 */
void cvm_hal_watchdog_feed(void);

/*
 * ── ALL OFF ──
 * Turn off ALL actuators immediately. Called on fault/estop.
 * The HAL should set every output to its safe state.
 */
void cvm_hal_all_off(void);

#ifdef __cplusplus
}
#endif

#endif /* CVM_HAL_H */