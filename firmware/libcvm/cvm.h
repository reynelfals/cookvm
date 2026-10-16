/*
 * CVM — Cooking Virtual Machine
 * Public API
 *
 * Portable C99 library for programmable cooking appliance control.
 * No dynamic allocation. No platform dependencies.
 * Implement cvm_hal.h for your hardware.
 *
 * Usage:
 *   1. Implement cvm_hal.h functions for your MCU
 *   2. Call cvm_init() once at startup
 *   3. Call cvm_tick() every TICK_MS from your main loop
 *   4. Call cvm_handle_command() when a message arrives from the brain
 *
 * SPDX-License-Identifier: Apache-2.0
 * Copyright 2026 the CookVM authors
 */

#ifndef CVM_H
#define CVM_H

#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

/* ═══════════════════════════════════════
   CONFIGURATION — adjust for your machine
   ═══════════════════════════════════════ */

#ifndef CVM_MAX_ACTUATORS
#define CVM_MAX_ACTUATORS   8
#endif

#ifndef CVM_MAX_SENSORS
#define CVM_MAX_SENSORS     4
#endif

#ifndef CVM_MAX_PROG
#define CVM_MAX_PROG        128   /* Max VM instructions */
#endif

#ifndef CVM_NUM_REGS
#define CVM_NUM_REGS        8     /* Float registers R0–R7 */
#endif

#ifndef CVM_MAX_JUMPS_TICK
#define CVM_MAX_JUMPS_TICK  10    /* Infinite loop protection */
#endif

#ifndef CVM_MSG_BUF
#define CVM_MSG_BUF         256   /* Max message length */
#endif

/* Sentinel: target is "off" (regulation disabled).
 * Distinct from TARGET 0 which means "regulate to 0°C"
 * (valid for refrigerators/freezers). */
#define CVM_TARGET_OFF      INT32_MIN

#ifndef CVM_TICK_MS
#define CVM_TICK_MS         200   /* Control loop period */
#endif

#ifndef CVM_NAME_LEN
#define CVM_NAME_LEN        12    /* Max actuator/sensor name length */
#endif

#ifndef CVM_TEXT_LEN
#define CVM_TEXT_LEN        20    /* Max EMIT/LABEL text length */
#endif


/* ═══════════════════════════════════════
   TYPES
   ═══════════════════════════════════════ */

/* Actuator types */
typedef enum {
    CVM_ACT_BINARY = 0,       /* On/off (0 or 1) */
    CVM_ACT_PROPORTIONAL,     /* 0–10000 (0.00–100.00%) */
} cvm_act_type_t;

/* Sensor types */
typedef enum {
    CVM_SENS_TEMPERATURE = 0, /* millidegrees C (°C × 1000) */
    CVM_SENS_PRESSURE,        /* millibars */
    CVM_SENS_MASS,            /* milligrams */
    CVM_SENS_HUMIDITY,        /* 0.001% */
    CVM_SENS_GENERIC,         /* raw integer */
} cvm_sens_type_t;

/* Machine modes (v2.0: HOLD removed — regulation is a custom instruction) */
typedef enum {
    CVM_MODE_IDLE = 0,
    CVM_MODE_DIRECT,
    CVM_MODE_SEQUENCE,
    CVM_MODE_PAUSED,
    CVM_MODE_CALIBRATE,
    CVM_MODE_TUNING,
    CVM_MODE_FAULT,
    CVM_MODE_ESTOP,
    CVM_NUM_MODES
} cvm_mode_t;

/* Disconnect policy */
typedef enum {
    CVM_DC_CONTINUE = 0,
    CVM_DC_PAUSE,
    CVM_DC_STOP,
    CVM_DC_ESTOP,
} cvm_dc_policy_t;

/* VM opcodes (v2.0: CONTROL/TARGET/TARGET_REG removed — use custom instructions) */
typedef enum {
    CVM_OP_NOP = 0,
    CVM_OP_SET,           /* SET <actuator> <value> */
    CVM_OP_SET_REG,       /* SET_REG <actuator> <Rn> */
    CVM_OP_WAIT,          /* WAIT <seconds> */
    CVM_OP_WAIT_GE,       /* WAIT_GE <sensor> <value> */
    CVM_OP_WAIT_LE,       /* WAIT_LE <sensor> <value> */
    CVM_OP_SET_R,         /* SET_R <Rn> <value> */
    CVM_OP_LOAD,          /* LOAD <Rn> <sensor> */
    CVM_OP_ADD,           /* ADD <Rn> <value> */
    CVM_OP_SUB,           /* SUB <Rn> <value> */
    CVM_OP_JMP,           /* JMP <step> */
    CVM_OP_JGT,           /* JGT <Rn> <value> <step> */
    CVM_OP_JLT,           /* JLT <Rn> <value> <step> */
    CVM_OP_DJNZ,          /* DJNZ <Rn> <step> */
    CVM_OP_EMIT,          /* EMIT <text> */
    CVM_OP_PROMPT,        /* PROMPT <text> — blocks VM until ACK */
    CVM_OP_LABEL,         /* LABEL <text> */
    CVM_OP_DISCONNECT,    /* DISCONNECT <policy> */
    CVM_OP_HALT,
    /* Custom instruction opcodes (machine-declared via INST in CAPABILITY) */
    CVM_OP_CUSTOM_HOLD,       /* HOLD <sensor> <value> */
    CVM_OP_CUSTOM_HOLD_OFF,   /* HOLD_OFF */
    CVM_OP_CUSTOM_CEILING,    /* CEILING <sensor> <value> */
    CVM_OP_CUSTOM_BAND,       /* BAND <value> */
    CVM_NUM_OPS
} cvm_opcode_t;


/* ═══════════════════════════════════════
   STRUCTURES
   ═══════════════════════════════════════ */

/* Actuator declaration */
typedef struct {
    char         name[CVM_NAME_LEN];
    cvm_act_type_t type;
    int32_t      range_min;
    int32_t      range_max;
    int32_t      current;       /* Current value */
} cvm_actuator_t;

/* Sensor declaration */
typedef struct {
    char          name[CVM_NAME_LEN];
    cvm_sens_type_t type;
    int32_t       value;         /* Latest reading (millidegrees, etc.) */
    int32_t       filtered;      /* Low-pass filtered value */
    int32_t       trend;         /* Rate of change (units per minute × 1000) */
    int32_t       prev_filtered;
    uint32_t      prev_ms;
    bool          valid;
    bool          seeded;
    uint32_t      fault_start;   /* When fault began (0 = no fault) */
    /* Ceiling (soft limit) */
    int32_t       ceiling;       /* 0 = disabled */
    bool          ceiling_hit;
} cvm_sensor_t;

/* VM instruction */
typedef struct {
    cvm_opcode_t  op;
    uint8_t       arg_u8;       /* Register, actuator, sensor index */
    uint8_t       arg_step;     /* Jump target */
    int32_t       arg_i1;       /* Value (millidegrees, ms, etc.) */
    int32_t       arg_i2;       /* Second value (JGT/JLT threshold) */
    char          text[CVM_TEXT_LEN];
} cvm_instruction_t;

/* Control tuning parameters */
typedef struct {
    int32_t  prop_band;         /* Proportional band (millidegrees) */
    int32_t  anticipation_ms;   /* Lookahead time (milliseconds) */
    uint16_t cycle_ms;          /* Relay duty cycle period */
    /* Step-response characterization results */
    int32_t  char_rise_rate;    /* millidegrees per minute */
    int32_t  char_coast;        /* millidegrees overshoot */
    int32_t  char_lag_ms;       /* Dead time in ms */
} cvm_tuning_t;

/* Persistent configuration */
typedef struct {
    uint32_t    magic;
    uint8_t     num_actuators;
    uint8_t     num_sensors;
    int32_t     sensor_fault_ms;
    uint32_t    heartbeat_timeout_ms;
    int32_t     hold_band;          /* Default hysteresis (millidegrees) */
    cvm_tuning_t tuning;
    uint32_t    crc;
} cvm_config_t;

/* Complete machine state */
typedef struct {
    /* Mode */
    cvm_mode_t       mode;
    char             fault_reason[24];

    /* Actuators and sensors */
    cvm_actuator_t   actuators[CVM_MAX_ACTUATORS];
    uint8_t          num_actuators;
    cvm_sensor_t     sensors[CVM_MAX_SENSORS];
    uint8_t          num_sensors;

    /* Control */
    uint8_t          control_sensor;    /* Index of sensor controlling heater */
    uint8_t          heat_actuator;     /* Index of heater actuator */
    int32_t          target;            /* Target value (millidegrees) */
    int32_t          band;              /* Hysteresis band (millidegrees) */
    cvm_dc_policy_t  dc_policy;

    /* Delta-T (sensor[0] − sensor[1], or first two sensors) */
    int32_t          delta_t;
    int32_t          delta_t_trend;
    int32_t          prev_delta_t;
    uint32_t         prev_delta_t_ms;
    bool             delta_t_seeded;

    /* Duty tracking */
    uint32_t         heater_on_accum;
    uint32_t         duty_window_start;
    int32_t          heater_duty;       /* 0–10000 (0.00–100.00%) */
    uint32_t         cycle_start;

    /* Heartbeat */
    uint32_t         last_heartbeat;

    /* VM state */
    cvm_instruction_t program[CVM_MAX_PROG];
    uint8_t          prog_len;
    uint8_t          vm_pc;
    bool             vm_waiting;
    uint32_t         vm_wait_start;
    uint32_t         vm_pause_elapsed;
    bool             prompt_waiting;    /* Blocked on PROMPT, waiting for ACK */

    /* Custom instruction state: HOLD (temperature regulation) */
    bool             hold_active;       /* HOLD is currently regulating */

    /* Registers */
    float            regs[CVM_NUM_REGS];

    /* Timing */
    uint32_t         uptime;

    /* Configuration */
    cvm_config_t     config;

    /* Connected flag (set by user code) */
    bool             connected;
} cvm_state_t;


/* ═══════════════════════════════════════
   PUBLIC API
   ═══════════════════════════════════════ */

/*
 * Initialize the CVM state machine.
 * Call once at startup after implementing the HAL.
 * Loads config from flash if valid, otherwise uses defaults.
 */
void cvm_init(cvm_state_t* s);

/*
 * Declare an actuator. Call before cvm_init() or after for hot-add.
 * Returns the actuator index, or -1 if full.
 */
int cvm_add_actuator(cvm_state_t* s, const char* name,
                     cvm_act_type_t type, int32_t range_min, int32_t range_max);

/*
 * Declare a sensor. Call before cvm_init() or after for hot-add.
 * Returns the sensor index, or -1 if full.
 */
int cvm_add_sensor(cvm_state_t* s, const char* name, cvm_sens_type_t type);

/*
 * Designate which actuator is the "heater" (controlled by TARGET).
 * Designate which sensor is the default control sensor.
 */
void cvm_set_heat_actuator(cvm_state_t* s, uint8_t actuator_index);
void cvm_set_control_sensor(cvm_state_t* s, uint8_t sensor_index);

/*
 * Main tick — call every CVM_TICK_MS from your control loop.
 * Reads sensors, checks safety, runs VM, controls heater.
 */
void cvm_tick(cvm_state_t* s);

/*
 * Handle a command string from the brain.
 * Call when a message is received (BLE, Serial, TCP, etc.)
 * Sends response via cvm_hal_send().
 */
void cvm_handle_command(cvm_state_t* s, const char* command);

/*
 * Notify the CVM that the brain has connected or disconnected.
 * On disconnect, the CVM applies the disconnect policy.
 */
void cvm_on_connect(cvm_state_t* s);
void cvm_on_disconnect(cvm_state_t* s);

/*
 * Emergency stop — callable from any context (ISR-safe if HAL is).
 */
void cvm_estop(cvm_state_t* s);

/*
 * Send periodic status broadcast.
 * Call from your main loop at ~1Hz when connected.
 */
void cvm_broadcast_status(cvm_state_t* s);

/*
 * Save/load configuration to persistent storage.
 */
bool cvm_save_config(cvm_state_t* s);
bool cvm_load_config(cvm_state_t* s);


/* ═══════════════════════════════════════
   UTILITY
   ═══════════════════════════════════════ */

/* Convert millidegrees to float °C */
static inline float cvm_to_celsius(int32_t millideg) {
    return millideg / 1000.0f;
}

/* Convert float °C to millidegrees */
static inline int32_t cvm_from_celsius(float c) {
    return (int32_t)(c * 1000.0f);
}

/* Get mode name string */
const char* cvm_mode_name(cvm_mode_t mode);

/* Get opcode name string */
const char* cvm_opcode_name(cvm_opcode_t op);

/* Find actuator index by name. Returns -1 if not found. */
int cvm_find_actuator(const cvm_state_t* s, const char* name);

/* Find sensor index by name. Returns -1 if not found. */
int cvm_find_sensor(const cvm_state_t* s, const char* name);


#ifdef __cplusplus
}
#endif

#endif /* CVM_H */