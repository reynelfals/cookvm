/*
 * CVM — Cooking Virtual Machine
 * Core Implementation
 *
 * Pure C99. No dynamic allocation. No platform dependencies.
 * All hardware access goes through cvm_hal.h.
 *
 * SPDX-License-Identifier: Apache-2.0
 * Copyright 2026 the CookVM authors
 */

#include "cvm.h"
#include "cvm_hal.h"
#include <string.h>
#include <stdio.h>
#include <stdarg.h>
#include <math.h>

/* ═══════════════════════════════════════
   CONSTANTS
   ═══════════════════════════════════════ */

#define CONFIG_MAGIC    0x43564D01  /* "CVM\x01" */
#define FILTER_ALPHA    300         /* EMA alpha × 1000 (0.3) */
#define TREND_PERIOD_MS 3000
#define DT_PERIOD_MS    5000
#define DUTY_WINDOW_MS  5000
#define CEILING_HYST    5000       /* 5°C in millidegrees */

static const char* MODE_NAMES[] = {
    "IDLE","DIRECT","SEQUENCE","PAUSED",
    "CALIBRATE","TUNING","FAULT","ESTOP"
};

static const char* OP_NAMES[] = {
    "NOP","SET","SET_REG",
    "WAIT","WAIT_GE","WAIT_LE",
    "SET_R","LOAD","ADD","SUB",
    "JMP","JGT","JLT","DJNZ",
    "EMIT","PROMPT","LABEL","DISCONNECT","HALT",
    "HOLD","HOLD_OFF","CEILING","BAND"
};


/* ═══════════════════════════════════════
   UTILITY
   ═══════════════════════════════════════ */

const char* cvm_mode_name(cvm_mode_t mode) {
    if (mode < CVM_NUM_MODES) return MODE_NAMES[mode];
    return "?";
}

const char* cvm_opcode_name(cvm_opcode_t op) {
    if (op < CVM_NUM_OPS) return OP_NAMES[op];
    return "?";
}

int cvm_find_actuator(const cvm_state_t* s, const char* name) {
    for (int i = 0; i < s->num_actuators; i++) {
        if (strcmp(s->actuators[i].name, name) == 0) return i;
    }
    return -1;
}

int cvm_find_sensor(const cvm_state_t* s, const char* name) {
    for (int i = 0; i < s->num_sensors; i++) {
        if (strcmp(s->sensors[i].name, name) == 0) return i;
    }
    return -1;
}

static void send_fmt(const char* fmt, ...) {
    char buf[CVM_MSG_BUF];
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(buf, sizeof(buf), fmt, ap);
    va_end(ap);
    cvm_hal_send(buf);
}

static uint32_t cfg_crc(const cvm_config_t* c) {
    uint32_t sum = 0;
    const uint8_t* p = (const uint8_t*)c;
    size_t len = offsetof(cvm_config_t, crc);
    for (size_t i = 0; i < len; i++) sum += p[i] * (i + 1);
    return sum ^ 0xDEADBEEF;
}

/* Case-insensitive compare */
static bool streqi(const char* a, const char* b) {
    while (*a && *b) {
        char ca = *a, cb = *b;
        if (ca >= 'a' && ca <= 'z') ca -= 32;
        if (cb >= 'a' && cb <= 'z') cb -= 32;
        if (ca != cb) return false;
        a++; b++;
    }
    return *a == *b;
}

/* Parse a float from string */
static float parse_float(const char* s) {
    float result = 0.0f;
    float sign = 1.0f;
    if (*s == '-') { sign = -1.0f; s++; }
    while (*s >= '0' && *s <= '9') { result = result * 10.0f + (*s - '0'); s++; }
    if (*s == '.') {
        s++;
        float frac = 0.1f;
        while (*s >= '0' && *s <= '9') { result += (*s - '0') * frac; frac *= 0.1f; s++; }
    }
    return result * sign;
}

/* Parse an integer from string */
static int32_t parse_int(const char* s) {
    int32_t result = 0;
    int32_t sign = 1;
    if (*s == '-') { sign = -1; s++; }
    while (*s >= '0' && *s <= '9') { result = result * 10 + (*s - '0'); s++; }
    return result * sign;
}

/* Tokenize a string by spaces. Returns token count. */
#define MAX_TOKENS 8
static int tokenize(const char* str, char tokens[][CVM_NAME_LEN], int max_tokens) {
    int count = 0;
    const char* p = str;
    while (*p && count < max_tokens) {
        while (*p == ' ') p++;
        if (!*p) break;
        int len = 0;
        while (*p && *p != ' ' && len < CVM_NAME_LEN - 1) {
            tokens[count][len++] = *p++;
        }
        tokens[count][len] = '\0';
        count++;
    }
    return count;
}


/* ═══════════════════════════════════════
   INIT
   ═══════════════════════════════════════ */

int cvm_add_actuator(cvm_state_t* s, const char* name,
                     cvm_act_type_t type, int32_t range_min, int32_t range_max) {
    if (s->num_actuators >= CVM_MAX_ACTUATORS) return -1;
    int idx = s->num_actuators;
    cvm_actuator_t* a = &s->actuators[idx];
    memset(a, 0, sizeof(*a));
    strncpy(a->name, name, CVM_NAME_LEN - 1);
    a->type = type;
    a->range_min = range_min;
    a->range_max = range_max;
    a->current = 0;
    s->num_actuators++;
    return idx;
}

int cvm_add_sensor(cvm_state_t* s, const char* name, cvm_sens_type_t type) {
    if (s->num_sensors >= CVM_MAX_SENSORS) return -1;
    int idx = s->num_sensors;
    cvm_sensor_t* se = &s->sensors[idx];
    memset(se, 0, sizeof(*se));
    strncpy(se->name, name, CVM_NAME_LEN - 1);
    se->type = type;
    se->valid = false;
    se->seeded = false;
    s->num_sensors++;
    return idx;
}

void cvm_set_heat_actuator(cvm_state_t* s, uint8_t idx) {
    s->heat_actuator = idx;
}

void cvm_set_control_sensor(cvm_state_t* s, uint8_t idx) {
    s->control_sensor = idx;
}

void cvm_init(cvm_state_t* s) {
    /* Don't zero actuator/sensor declarations — they were set by user */
    s->mode = CVM_MODE_IDLE;
    s->target = CVM_TARGET_OFF;
    s->band = 2000;  /* 2°C default */
    s->dc_policy = CVM_DC_CONTINUE;
    s->prog_len = 0;
    s->vm_pc = 0;
    s->vm_waiting = false;
    s->prompt_waiting = false;
    s->hold_active = false;
    s->delta_t_seeded = false;
    s->connected = false;
    s->heater_on_accum = 0;
    s->heater_duty = 0;
    s->cycle_start = 0;
    s->duty_window_start = cvm_hal_millis();
    s->last_heartbeat = cvm_hal_millis();
    s->uptime = 0;
    memset(s->fault_reason, 0, sizeof(s->fault_reason));
    memset(s->regs, 0, sizeof(s->regs));

    /* Load config */
    cvm_load_config(s);
    s->band = s->config.hold_band;
}


/* ═══════════════════════════════════════
   CONFIG PERSISTENCE
   ═══════════════════════════════════════ */

bool cvm_save_config(cvm_state_t* s) {
    s->config.magic = CONFIG_MAGIC;
    s->config.crc = cfg_crc(&s->config);
    return cvm_hal_config_save(&s->config, sizeof(s->config));
}

bool cvm_load_config(cvm_state_t* s) {
    cvm_config_t tmp;
    if (!cvm_hal_config_load(&tmp, sizeof(tmp))) goto defaults;
    if (tmp.magic != CONFIG_MAGIC) goto defaults;
    if (cfg_crc(&tmp) != tmp.crc) goto defaults;
    s->config = tmp;
    return true;

defaults:
    memset(&s->config, 0, sizeof(s->config));
    s->config.magic = CONFIG_MAGIC;
    s->config.hold_band = 2000;                 /* 2.0°C */
    s->config.heartbeat_timeout_ms = 30000;
    s->config.sensor_fault_ms = 5000;
    s->config.tuning.prop_band = 7425;          /* 7.4°C — from running machine */
    s->config.tuning.anticipation_ms = 30000;   /* 30s */
    s->config.tuning.cycle_ms = 20000;          /* 20s */
    s->config.tuning.char_rise_rate = 0;
    s->config.tuning.char_coast = 3000;         /* 3.0°C */
    s->config.tuning.char_lag_ms = 192000;      /* 192s */
    s->config.crc = cfg_crc(&s->config);
    return false;
}


/* ═══════════════════════════════════════
   SENSORS
   ═══════════════════════════════════════ */

static void update_sensor(cvm_state_t* s, uint8_t idx) {
    cvm_sensor_t* se = &s->sensors[idx];
    int32_t raw = cvm_hal_read_sensor(idx);
    bool hw_valid = cvm_hal_sensor_valid(idx);
    uint32_t now = cvm_hal_millis();

    if (!hw_valid || raw == CVM_SENSOR_INVALID) {
        if (se->fault_start == 0) se->fault_start = now;
        if (now - se->fault_start > (uint32_t)s->config.sensor_fault_ms) {
            se->valid = false;
        }
        return;
    }

    se->fault_start = 0;
    se->valid = true;
    se->value = raw;

    /* EMA filter */
    if (!se->seeded) {
        se->filtered = raw;
        se->seeded = true;
        se->prev_filtered = raw;
        se->prev_ms = now;
        se->trend = 0;
    } else {
        se->filtered += (int32_t)((int64_t)(raw - se->filtered) * FILTER_ALPHA / 1000);

        /* Trend every TREND_PERIOD_MS */
        if (now - se->prev_ms >= TREND_PERIOD_MS) {
            int32_t dt_ms = (int32_t)(now - se->prev_ms);
            /* trend = (delta / dt_ms) × 60000 = delta_per_minute in millidegrees */
            se->trend = (int32_t)((int64_t)(se->filtered - se->prev_filtered) * 60000 / dt_ms);
            se->prev_filtered = se->filtered;
            se->prev_ms = now;
        }
    }
}

static void update_all_sensors(cvm_state_t* s) {
    for (uint8_t i = 0; i < s->num_sensors; i++) {
        update_sensor(s, i);
    }
}

static void update_delta_t(cvm_state_t* s) {
    if (s->num_sensors < 2) return;
    if (!s->sensors[0].valid || !s->sensors[1].valid) return;

    s->delta_t = s->sensors[0].filtered - s->sensors[1].filtered;
    uint32_t now = cvm_hal_millis();

    if (!s->delta_t_seeded) {
        s->prev_delta_t = s->delta_t;
        s->prev_delta_t_ms = now;
        s->delta_t_seeded = true;
        s->delta_t_trend = 0;
        return;
    }

    if (now - s->prev_delta_t_ms >= DT_PERIOD_MS) {
        int32_t dt_ms = (int32_t)(now - s->prev_delta_t_ms);
        s->delta_t_trend = (int32_t)((int64_t)(s->delta_t - s->prev_delta_t) * 60000 / dt_ms);
        s->prev_delta_t = s->delta_t;
        s->prev_delta_t_ms = now;
    }
}


/* ═══════════════════════════════════════
   SAFETY
   ═══════════════════════════════════════ */

static void enter_fault(cvm_state_t* s, const char* reason) {
    cvm_hal_all_off();
    s->mode = CVM_MODE_FAULT;
    s->hold_active = false;
    s->prompt_waiting = false;
    strncpy(s->fault_reason, reason, sizeof(s->fault_reason) - 1);
    /* Zero all actuator tracking */
    for (uint8_t i = 0; i < s->num_actuators; i++) s->actuators[i].current = 0;
}

static bool check_safety(cvm_state_t* s) {
    /* Sensor validity */
    for (uint8_t i = 0; i < s->num_sensors; i++) {
        if (!s->sensors[i].valid) {
            char reason[24];
            snprintf(reason, sizeof(reason), "SENSOR_%s", s->sensors[i].name);
            enter_fault(s, reason);
            return false;
        }
    }

    /* Sensor ceilings (soft limits set per-sensor) */
    for (uint8_t i = 0; i < s->num_sensors; i++) {
        cvm_sensor_t* se = &s->sensors[i];
        if (se->ceiling > 0 && se->filtered > se->ceiling) {
            /* Suppress heater — not a fault, just throttle */
            cvm_hal_set_actuator(s->heat_actuator, 0);
            s->actuators[s->heat_actuator].current = 0;
            se->ceiling_hit = true;
            return true;  /* Not a fault */
        }
        if (se->ceiling_hit && se->filtered < se->ceiling - CEILING_HYST) {
            se->ceiling_hit = false;
        }
    }

    /* Heartbeat timeout in DIRECT mode */
    if (s->mode == CVM_MODE_DIRECT && s->actuators[s->heat_actuator].current > 0) {
        if (cvm_hal_millis() - s->last_heartbeat > s->config.heartbeat_timeout_ms) {
            enter_fault(s, "HEARTBEAT");
            return false;
        }
    }

    return true;
}


/* ═══════════════════════════════════════
   CONTROLLER (time-proportioning)
   ═══════════════════════════════════════ */

static void control_heater(cvm_state_t* s) {
    /* When target is CVM_TARGET_OFF, regulation is disabled.
     * The heater is NOT forced off — SET commands from the program
     * or DIRECT mode control the heater directly.
     * Safety ceilings still run (checked in check_safety before this).
     * TARGET 0 means "regulate to 0°C" (valid for fridge/freezer).
     * See CookVM Spec section 5.1.1. */
    if (s->target == CVM_TARGET_OFF) {
        s->heater_duty = 0;
        return;  /* Don't touch the heater actuator */
    }

    uint8_t si = s->control_sensor;
    if (si >= s->num_sensors || !s->sensors[si].valid) {
        cvm_hal_set_actuator(s->heat_actuator, 0);
        s->actuators[s->heat_actuator].current = 0;
        return;
    }

    /* Check if any ceiling is suppressing */
    for (uint8_t i = 0; i < s->num_sensors; i++) {
        if (s->sensors[i].ceiling_hit) {
            cvm_hal_set_actuator(s->heat_actuator, 0);
            s->actuators[s->heat_actuator].current = 0;
            return;
        }
    }

    int32_t temp = s->sensors[si].filtered;
    int32_t trend = s->sensors[si].trend;  /* millideg/min */
    int32_t error = s->target - temp;

    /* Anticipatory correction */
    int32_t antic_ms = s->config.tuning.anticipation_ms;
    if (antic_ms > 0 && trend > 0 && error > 0) {
        /* predicted rise = trend × (antic_ms / 60000) */
        int32_t predicted = (int32_t)((int64_t)trend * antic_ms / 60000);
        error -= predicted;
    }

    /* Proportional duty */
    int32_t prop = s->config.tuning.prop_band;
    int32_t duty;  /* 0–10000 */
    if (prop <= 0) prop = 10000;

    if (error >= prop) {
        duty = 10000;
    } else if (error <= 0) {
        duty = 0;
    } else {
        duty = (int32_t)((int64_t)error * 10000 / prop);
    }

    if (duty < 500)  duty = 0;      /* Below 5% → off */
    if (duty > 9500) duty = 10000;  /* Above 95% → full on */

    /* Time-proportioning */
    uint32_t now = cvm_hal_millis();
    uint16_t cycle = s->config.tuning.cycle_ms;
    if (cycle < 5000) cycle = 20000;

    if (now - s->cycle_start >= cycle) {
        s->cycle_start = now;
    }

    uint32_t elapsed = now - s->cycle_start;
    uint32_t on_time = (uint32_t)((uint64_t)duty * cycle / 10000);
    bool heater_on;

    if (duty >= 9500)    heater_on = true;
    else if (duty <= 0)  heater_on = false;
    else                 heater_on = (elapsed < on_time);

    int32_t val = heater_on ? s->actuators[s->heat_actuator].range_max : 0;
    cvm_hal_set_actuator(s->heat_actuator, val);
    s->actuators[s->heat_actuator].current = val;

    /* Duty tracking */
    if (now - s->duty_window_start >= DUTY_WINDOW_MS) {
        s->heater_duty = (int32_t)((int64_t)s->heater_on_accum * 10000 / DUTY_WINDOW_MS);
        s->heater_on_accum = 0;
        s->duty_window_start = now;
    }
    if (heater_on) s->heater_on_accum += CVM_TICK_MS;
}


/* ═══════════════════════════════════════
   VM EXECUTION
   ═══════════════════════════════════════ */

static volatile bool vm_force_next = false;
static char emit_buf[CVM_TEXT_LEN + 8];
static volatile bool emit_pending = false;

static void vm_reset(cvm_state_t* s) {
    s->vm_pc = 0;
    s->vm_waiting = false;
    s->vm_wait_start = 0;
    s->vm_pause_elapsed = 0;
    s->prompt_waiting = false;
    s->hold_active = false;
    memset(s->regs, 0, sizeof(s->regs));
}

static void vm_tick(cvm_state_t* s) {
    if (s->mode != CVM_MODE_SEQUENCE) return;
    int jumps = 0;

    while (s->vm_pc < s->prog_len && jumps < CVM_MAX_JUMPS_TICK) {

        /* Blocked on PROMPT? Wait for ACK (or force-next) */
        if (s->prompt_waiting) {
            if (vm_force_next) {
                vm_force_next = false;
                s->prompt_waiting = false;
                s->vm_pc++;
                continue;
            }
            return;  /* Stay blocked until ACK */
        }

        /* Blocked on WAIT? */
        if (s->vm_waiting) {
            if (vm_force_next) {
                vm_force_next = false;
                s->vm_waiting = false;
                s->vm_pc++;
                continue;
            }

            cvm_instruction_t* ins = &s->program[s->vm_pc];
            bool done = false;

            switch (ins->op) {
                case CVM_OP_WAIT:
                    done = (cvm_hal_millis() - s->vm_wait_start >=
                            (uint32_t)(ins->arg_i1));
                    break;
                case CVM_OP_WAIT_GE:
                    if (ins->arg_u8 < s->num_sensors && s->sensors[ins->arg_u8].valid)
                        done = s->sensors[ins->arg_u8].filtered >= ins->arg_i1;
                    if (!done && ins->arg_i2 > 0) {
                        if (cvm_hal_millis() - s->vm_wait_start >= (uint32_t)ins->arg_i2) {
                            done = true;
                            snprintf(emit_buf, sizeof(emit_buf), "EVENT TIMEOUT_WAIT_GE");
                            emit_pending = true;
                        }
                    }
                    break;
                case CVM_OP_WAIT_LE:
                    if (ins->arg_u8 < s->num_sensors && s->sensors[ins->arg_u8].valid)
                        done = s->sensors[ins->arg_u8].filtered <= ins->arg_i1;
                    if (!done && ins->arg_i2 > 0) {
                        if (cvm_hal_millis() - s->vm_wait_start >= (uint32_t)ins->arg_i2) {
                            done = true;
                            snprintf(emit_buf, sizeof(emit_buf), "EVENT TIMEOUT_WAIT_LE");
                            emit_pending = true;
                        }
                    }
                    break;
                default:
                    done = true;
            }
            if (!done) return;
            s->vm_waiting = false;
            s->vm_pc++;
            continue;
        }

        /* Fetch & execute */
        cvm_instruction_t* ins = &s->program[s->vm_pc];

        switch (ins->op) {
            case CVM_OP_NOP:
            case CVM_OP_LABEL:
                s->vm_pc++;
                break;

            case CVM_OP_SET: {
                if (ins->arg_u8 < s->num_actuators) {
                    int32_t v = ins->arg_i1;
                    cvm_actuator_t* a = &s->actuators[ins->arg_u8];
                    if (v < a->range_min) v = a->range_min;
                    if (v > a->range_max) v = a->range_max;
                    cvm_hal_set_actuator(ins->arg_u8, v);
                    a->current = v;
                    /* Precedence: SET on heat_actuator releases HOLD */
                    if (ins->arg_u8 == s->heat_actuator && s->hold_active) {
                        s->hold_active = false;
                        s->target = CVM_TARGET_OFF;
                        snprintf(emit_buf, sizeof(emit_buf), "EVENT HOLD_RELEASED_BY_SET");
                        emit_pending = true;
                    }
                }
                s->vm_pc++;
                break;
            }

            case CVM_OP_SET_REG:
                if (ins->arg_u8 < s->num_actuators && ins->arg_step < CVM_NUM_REGS) {
                    int32_t v = (int32_t)s->regs[ins->arg_step];
                    cvm_actuator_t* a = &s->actuators[ins->arg_u8];
                    if (v < a->range_min) v = a->range_min;
                    if (v > a->range_max) v = a->range_max;
                    cvm_hal_set_actuator(ins->arg_u8, v);
                    a->current = v;
                    /* Precedence: SET_REG on heat_actuator releases HOLD */
                    if (ins->arg_u8 == s->heat_actuator && s->hold_active) {
                        s->hold_active = false;
                        s->target = CVM_TARGET_OFF;
                        snprintf(emit_buf, sizeof(emit_buf), "EVENT HOLD_RELEASED_BY_SET");
                        emit_pending = true;
                    }
                }
                s->vm_pc++;
                break;

            /* ── Custom instructions: HOLD / HOLD_OFF / CEILING / BAND ── */

            case CVM_OP_CUSTOM_HOLD:
                if (ins->arg_u8 < s->num_sensors) {
                    s->control_sensor = ins->arg_u8;
                    s->target = ins->arg_i1;
                    s->hold_active = true;
                    /* Auto-ceiling if none set */
                    if (s->num_sensors > 0 && s->sensors[0].ceiling <= 0 && s->target > 0) {
                        s->sensors[0].ceiling = s->target + 60000;  /* +60°C */
                    }
                    snprintf(emit_buf, sizeof(emit_buf), "EVENT HOLD_STARTED");
                    emit_pending = true;
                }
                s->vm_pc++;
                break;

            case CVM_OP_CUSTOM_HOLD_OFF:
                s->hold_active = false;
                s->target = CVM_TARGET_OFF;
                cvm_hal_set_actuator(s->heat_actuator, 0);
                s->actuators[s->heat_actuator].current = 0;
                snprintf(emit_buf, sizeof(emit_buf), "EVENT HOLD_OFF");
                emit_pending = true;
                s->vm_pc++;
                break;

            case CVM_OP_CUSTOM_CEILING:
                if (ins->arg_u8 < s->num_sensors) {
                    s->sensors[ins->arg_u8].ceiling = ins->arg_i1;
                    s->sensors[ins->arg_u8].ceiling_hit = false;
                }
                s->vm_pc++;
                break;

            case CVM_OP_CUSTOM_BAND:
                s->band = ins->arg_i1;
                s->vm_pc++;
                break;

            case CVM_OP_WAIT:
            case CVM_OP_WAIT_GE:
            case CVM_OP_WAIT_LE:
                s->vm_waiting = true;
                s->vm_wait_start = cvm_hal_millis();
                return;

            case CVM_OP_SET_R:
                if (ins->arg_u8 < CVM_NUM_REGS) { s->regs[ins->arg_u8] = *(float*)&ins->arg_i1; }
                s->vm_pc++;
                break;

            case CVM_OP_LOAD:
                if (ins->arg_u8 < CVM_NUM_REGS && ins->arg_step < s->num_sensors) {
                    s->regs[ins->arg_u8] = cvm_to_celsius(s->sensors[ins->arg_step].filtered);
                }
                s->vm_pc++;
                break;

            case CVM_OP_ADD:
                if (ins->arg_u8 < CVM_NUM_REGS) { s->regs[ins->arg_u8] += *(float*)&ins->arg_i1; }
                s->vm_pc++;
                break;

            case CVM_OP_SUB:
                if (ins->arg_u8 < CVM_NUM_REGS) { s->regs[ins->arg_u8] -= *(float*)&ins->arg_i1; }
                s->vm_pc++;
                break;

            case CVM_OP_JMP:
                s->vm_pc = ins->arg_step;
                jumps++;
                break;

            case CVM_OP_JGT:
                if (ins->arg_u8 < CVM_NUM_REGS &&
                    s->regs[ins->arg_u8] > *(float*)&ins->arg_i2) {
                    s->vm_pc = ins->arg_step;
                } else {
                    s->vm_pc++;
                }
                jumps++;
                break;

            case CVM_OP_JLT:
                if (ins->arg_u8 < CVM_NUM_REGS &&
                    s->regs[ins->arg_u8] < *(float*)&ins->arg_i2) {
                    s->vm_pc = ins->arg_step;
                } else {
                    s->vm_pc++;
                }
                jumps++;
                break;

            case CVM_OP_DJNZ:
                if (ins->arg_u8 < CVM_NUM_REGS) {
                    s->regs[ins->arg_u8] -= 1.0f;
                    if (s->regs[ins->arg_u8] > 0.0f) {
                        s->vm_pc = ins->arg_step;
                    } else {
                        s->vm_pc++;
                    }
                } else {
                    s->vm_pc++;
                }
                jumps++;
                break;

            case CVM_OP_EMIT:
                snprintf(emit_buf, sizeof(emit_buf), "EVENT %s", ins->text);
                emit_pending = true;
                s->vm_pc++;
                break;

            case CVM_OP_PROMPT:
                /* Send PROMPT to brain, block VM until ACK */
                snprintf(emit_buf, sizeof(emit_buf), "PROMPT %s", ins->text);
                emit_pending = true;
                s->prompt_waiting = true;
                s->vm_waiting = true;  /* STATUS shows wait=1 */
                return;

            case CVM_OP_DISCONNECT:
                s->dc_policy = (cvm_dc_policy_t)ins->arg_u8;
                s->vm_pc++;
                break;

            case CVM_OP_HALT:
                cvm_hal_all_off();
                s->target = CVM_TARGET_OFF;
                s->hold_active = false;
                for (uint8_t i = 0; i < s->num_actuators; i++) s->actuators[i].current = 0;
                s->mode = CVM_MODE_IDLE;
                snprintf(emit_buf, sizeof(emit_buf), "EVENT HALT");
                emit_pending = true;
                return;

            default:
                s->vm_pc++;
                break;
        }
    }

    if (s->vm_pc >= s->prog_len) {
        cvm_hal_all_off();
        s->target = CVM_TARGET_OFF;
        s->hold_active = false;
        s->mode = CVM_MODE_IDLE;
    }
}


/* ═══════════════════════════════════════
   MAIN TICK
   ═══════════════════════════════════════ */

void cvm_tick(cvm_state_t* s) {
    s->uptime = cvm_hal_millis();

    /* 1. Sensors */
    update_all_sensors(s);
    update_delta_t(s);

    /* 2. Safety */
    if (s->mode != CVM_MODE_FAULT && s->mode != CVM_MODE_ESTOP) {
        if (!check_safety(s)) return;
    }

    /* 3. Control */
    switch (s->mode) {
        case CVM_MODE_IDLE:
            /* Direct HOLD command outside of programs */
            if (s->hold_active) control_heater(s);
            break;
        case CVM_MODE_DIRECT:
            break;
        case CVM_MODE_SEQUENCE:
            vm_tick(s);
            if (s->hold_active) control_heater(s);
            break;
        default:
            break;
    }

    /* 4. Forward EMIT events */
    if (emit_pending && s->connected) {
        cvm_hal_send(emit_buf);
        emit_pending = false;
    }

    /* 5. Watchdog */
    cvm_hal_watchdog_feed();
}


/* ═══════════════════════════════════════
   COMMAND PARSER
   ═══════════════════════════════════════ */

static void parse_program_add(cvm_state_t* s, const char* line) {
    if (s->prog_len >= CVM_MAX_PROG) {
        send_fmt("ERR PROGRAM_FULL");
        return;
    }

    char tok[MAX_TOKENS][CVM_NAME_LEN];
    int nt = tokenize(line, tok, MAX_TOKENS);
    if (nt == 0) { send_fmt("ERR EMPTY_OP"); return; }

    cvm_instruction_t ins;
    memset(&ins, 0, sizeof(ins));

    /* Convert opcode */
    if      (streqi(tok[0], "NOP"))        ins.op = CVM_OP_NOP;
    else if (streqi(tok[0], "SET"))       { ins.op = CVM_OP_SET;
        int ai = cvm_find_actuator(s, tok[1]);
        if (ai < 0) { send_fmt("ERR BAD_ACTUATOR %s", tok[1]); return; }
        ins.arg_u8 = ai;
        ins.arg_i1 = parse_int(tok[2]);
    }
    else if (streqi(tok[0], "SET_REG"))   { ins.op = CVM_OP_SET_REG;
        int ai = cvm_find_actuator(s, tok[1]);
        if (ai < 0) { send_fmt("ERR BAD_ACTUATOR %s", tok[1]); return; }
        ins.arg_u8 = ai;
        ins.arg_step = (tok[2][0] == 'R' || tok[2][0] == 'r') ? tok[2][1] - '0' : tok[2][0] - '0';
    }
    /* Custom instructions: HOLD, HOLD_OFF, CEILING, BAND */
    else if (streqi(tok[0], "HOLD") && nt >= 3) { ins.op = CVM_OP_CUSTOM_HOLD;
        int si = cvm_find_sensor(s, tok[1]);
        if (si < 0) { send_fmt("ERR BAD_SENSOR %s", tok[1]); return; }
        ins.arg_u8 = si;
        ins.arg_i1 = cvm_from_celsius(parse_float(tok[2]));
    }
    else if (streqi(tok[0], "HOLD_OFF")) { ins.op = CVM_OP_CUSTOM_HOLD_OFF; }
    else if (streqi(tok[0], "CEILING"))   { ins.op = CVM_OP_CUSTOM_CEILING;
        int si = cvm_find_sensor(s, tok[1]);
        if (si < 0) { send_fmt("ERR BAD_SENSOR %s", tok[1]); return; }
        ins.arg_u8 = si;
        ins.arg_i1 = cvm_from_celsius(parse_float(tok[2]));
    }
    else if (streqi(tok[0], "BAND"))      { ins.op = CVM_OP_CUSTOM_BAND;
        ins.arg_i1 = cvm_from_celsius(parse_float(tok[1]));
    }
    else if (streqi(tok[0], "WAIT"))      { ins.op = CVM_OP_WAIT;
        ins.arg_i1 = (int32_t)(parse_float(tok[1]) * 1000);  /* seconds → ms */
    }
    else if (streqi(tok[0], "WAIT_GE"))   { ins.op = CVM_OP_WAIT_GE;
        int si = cvm_find_sensor(s, tok[1]);
        if (si < 0) { send_fmt("ERR BAD_SENSOR %s", tok[1]); return; }
        ins.arg_u8 = si;
        ins.arg_i1 = cvm_from_celsius(parse_float(tok[2]));
        if (nt >= 4) ins.arg_i2 = (int32_t)(parse_float(tok[3]) * 1000);  /* timeout s→ms */
    }
    else if (streqi(tok[0], "WAIT_LE"))   { ins.op = CVM_OP_WAIT_LE;
        int si = cvm_find_sensor(s, tok[1]);
        if (si < 0) { send_fmt("ERR BAD_SENSOR %s", tok[1]); return; }
        ins.arg_u8 = si;
        ins.arg_i1 = cvm_from_celsius(parse_float(tok[2]));
        if (nt >= 4) ins.arg_i2 = (int32_t)(parse_float(tok[3]) * 1000);  /* timeout s→ms */
    }
    else if (streqi(tok[0], "SET_R"))     { ins.op = CVM_OP_SET_R;
        ins.arg_u8 = (tok[1][0] == 'R' || tok[1][0] == 'r') ? tok[1][1] - '0' : tok[1][0] - '0';
        float v = parse_float(tok[2]);
        memcpy(&ins.arg_i1, &v, sizeof(float));
    }
    else if (streqi(tok[0], "LOAD"))      { ins.op = CVM_OP_LOAD;
        ins.arg_u8 = (tok[1][0] == 'R' || tok[1][0] == 'r') ? tok[1][1] - '0' : tok[1][0] - '0';
        int si = cvm_find_sensor(s, tok[2]);
        if (si < 0) { send_fmt("ERR BAD_SENSOR %s", tok[2]); return; }
        ins.arg_step = si;
    }
    else if (streqi(tok[0], "ADD"))       { ins.op = CVM_OP_ADD;
        ins.arg_u8 = (tok[1][0] == 'R' || tok[1][0] == 'r') ? tok[1][1] - '0' : tok[1][0] - '0';
        float v = parse_float(tok[2]);
        memcpy(&ins.arg_i1, &v, sizeof(float));
    }
    else if (streqi(tok[0], "SUB"))       { ins.op = CVM_OP_SUB;
        ins.arg_u8 = (tok[1][0] == 'R' || tok[1][0] == 'r') ? tok[1][1] - '0' : tok[1][0] - '0';
        float v = parse_float(tok[2]);
        memcpy(&ins.arg_i1, &v, sizeof(float));
    }
    else if (streqi(tok[0], "JMP"))       { ins.op = CVM_OP_JMP;
        ins.arg_step = (uint8_t)parse_int(tok[1]);
    }
    else if (streqi(tok[0], "JGT"))       { ins.op = CVM_OP_JGT;
        ins.arg_u8 = (tok[1][0] == 'R' || tok[1][0] == 'r') ? tok[1][1] - '0' : tok[1][0] - '0';
        float v = parse_float(tok[2]);
        memcpy(&ins.arg_i2, &v, sizeof(float));
        ins.arg_step = (uint8_t)parse_int(tok[3]);
    }
    else if (streqi(tok[0], "JLT"))       { ins.op = CVM_OP_JLT;
        ins.arg_u8 = (tok[1][0] == 'R' || tok[1][0] == 'r') ? tok[1][1] - '0' : tok[1][0] - '0';
        float v = parse_float(tok[2]);
        memcpy(&ins.arg_i2, &v, sizeof(float));
        ins.arg_step = (uint8_t)parse_int(tok[3]);
    }
    else if (streqi(tok[0], "DJNZ"))      { ins.op = CVM_OP_DJNZ;
        ins.arg_u8 = (tok[1][0] == 'R' || tok[1][0] == 'r') ? tok[1][1] - '0' : tok[1][0] - '0';
        ins.arg_step = (uint8_t)parse_int(tok[2]);
    }
    else if (streqi(tok[0], "EMIT"))      { ins.op = CVM_OP_EMIT;
        if (nt > 1) strncpy(ins.text, tok[1], CVM_TEXT_LEN - 1);
    }
    else if (streqi(tok[0], "PROMPT"))    { ins.op = CVM_OP_PROMPT;
        if (nt > 1) strncpy(ins.text, tok[1], CVM_TEXT_LEN - 1);
    }
    else if (streqi(tok[0], "LABEL"))     { ins.op = CVM_OP_LABEL;
        if (nt > 1) strncpy(ins.text, tok[1], CVM_TEXT_LEN - 1);
    }
    else if (streqi(tok[0], "DISCONNECT")){ ins.op = CVM_OP_DISCONNECT;
        if      (streqi(tok[1], "CONTINUE")) ins.arg_u8 = CVM_DC_CONTINUE;
        else if (streqi(tok[1], "PAUSE"))    ins.arg_u8 = CVM_DC_PAUSE;
        else if (streqi(tok[1], "STOP"))     ins.arg_u8 = CVM_DC_STOP;
        else if (streqi(tok[1], "ESTOP"))    ins.arg_u8 = CVM_DC_ESTOP;
    }
    else if (streqi(tok[0], "HALT"))      { ins.op = CVM_OP_HALT; }
    else {
        send_fmt("ERR BAD_OP %s", tok[0]);
        return;
    }

    s->program[s->prog_len++] = ins;
    send_fmt("OK [%d] %s", s->prog_len - 1, line);
}

void cvm_handle_command(cvm_state_t* s, const char* command) {
    char tok[MAX_TOKENS][CVM_NAME_LEN];
    int nt = tokenize(command, tok, MAX_TOKENS);
    if (nt == 0) return;

    /* PING */
    if (streqi(tok[0], "PING")) { cvm_hal_send("PONG"); return; }

    /* ESTOP */
    if (streqi(tok[0], "ESTOP")) { cvm_estop(s); send_fmt("OK ESTOP"); return; }

    /* CLEAR */
    if (streqi(tok[0], "CLEAR")) {
        if (s->mode == CVM_MODE_FAULT || s->mode == CVM_MODE_ESTOP) {
            cvm_hal_all_off();
            s->target = CVM_TARGET_OFF;
            s->mode = CVM_MODE_IDLE;
            memset(s->fault_reason, 0, sizeof(s->fault_reason));
        }
        send_fmt("OK CLEAR");
        return;
    }

    /* HEARTBEAT */
    if (streqi(tok[0], "HEARTBEAT") || streqi(tok[0], "HB")) {
        s->last_heartbeat = cvm_hal_millis();
        cvm_hal_send("OK");
        return;
    }

    /* STATUS */
    if (streqi(tok[0], "STATUS") || (tok[0][0] == '?' && tok[0][1] == '\0')) {
        cvm_broadcast_status(s);
        return;
    }

    /* CAPABILITY */
    if (streqi(tok[0], "CAPABILITY")) {
        send_fmt("COOKVM 2.0");
        for (uint8_t i = 0; i < s->num_actuators; i++) {
            cvm_actuator_t* a = &s->actuators[i];
            send_fmt("ACTUATOR %s type=%s range=%ld-%ld", a->name,
                a->type == CVM_ACT_BINARY ? "binary" : "proportional",
                (long)a->range_min, (long)a->range_max);
        }
        for (uint8_t i = 0; i < s->num_sensors; i++) {
            const char* types[] = {"temperature","pressure","mass","humidity","generic"};
            send_fmt("SENSOR %s type=%s", s->sensors[i].name,
                s->sensors[i].type < 5 ? types[s->sensors[i].type] : "generic");
        }
        /* Custom instructions */
        cvm_hal_send("INST HOLD args=sensor,value desc=regulate_heater_to_maintain_sensor_temperature");
        cvm_hal_send("INST HOLD_OFF args=none desc=stop_temperature_regulation");
        cvm_hal_send("INST CEILING args=sensor,value desc=suppress_heater_if_sensor_exceeds_value");
        cvm_hal_send("INST BAND args=value desc=set_hysteresis_band_for_regulation");
        cvm_hal_send("INST PROMPT args=text desc=notify_user_and_wait_for_acknowledgment");
        cvm_hal_send("END_CAPABILITY");
        return;
    }

    /* MODE */
    if (streqi(tok[0], "MODE") && nt > 1) {
        for (int i = 0; i < CVM_NUM_MODES; i++) {
            if (streqi(tok[1], MODE_NAMES[i]) && i != CVM_MODE_FAULT && i != CVM_MODE_ESTOP) {
                if (i == CVM_MODE_IDLE) { cvm_hal_all_off(); s->target = CVM_TARGET_OFF; }
                s->mode = (cvm_mode_t)i;
                if (i == CVM_MODE_DIRECT) s->last_heartbeat = cvm_hal_millis();
                send_fmt("OK MODE %s", MODE_NAMES[i]);
                return;
            }
        }
        send_fmt("ERR BAD_MODE %s", tok[1]);
        return;
    }

    /* ACK — release VM from PROMPT */
    if (streqi(tok[0], "ACK")) {
        if (s->prompt_waiting) {
            s->prompt_waiting = false;
            s->vm_waiting = false;
            s->vm_pc++;
            send_fmt("OK ACK");
        } else {
            send_fmt("ERR NO_PROMPT");
        }
        return;
    }

    /* HOLD <sensor> <target> — direct command (outside programs too) */
    if (streqi(tok[0], "HOLD") && nt >= 3) {
        int si = cvm_find_sensor(s, tok[1]);
        if (si < 0) { send_fmt("ERR BAD_SENSOR %s", tok[1]); return; }
        s->control_sensor = si;
        s->target = cvm_from_celsius(parse_float(tok[2]));
        s->band = s->config.hold_band;
        s->hold_active = true;
        /* Auto-ceiling */
        if (s->num_sensors > 0 && s->sensors[0].ceiling <= 0 && s->target > 0) {
            s->sensors[0].ceiling = s->target + 60000;
        }
        send_fmt("OK HOLD %s %.1f", tok[1], cvm_to_celsius(s->target));
        return;
    }

    /* HOLD_OFF — stop regulation */
    if (streqi(tok[0], "HOLD_OFF")) {
        s->hold_active = false;
        s->target = CVM_TARGET_OFF;
        cvm_hal_set_actuator(s->heat_actuator, 0);
        s->actuators[s->heat_actuator].current = 0;
        send_fmt("OK HOLD_OFF");
        return;
    }

    /* CEILING <sensor> <value> */
    if (streqi(tok[0], "CEILING") && nt >= 3) {
        int si = cvm_find_sensor(s, tok[1]);
        if (si < 0) { send_fmt("ERR BAD_SENSOR %s", tok[1]); return; }
        s->sensors[si].ceiling = cvm_from_celsius(parse_float(tok[2]));
        s->sensors[si].ceiling_hit = false;
        send_fmt("OK CEILING %s %.0f", tok[1], cvm_to_celsius(s->sensors[si].ceiling));
        return;
    }

    /* BAND <value> */
    if (streqi(tok[0], "BAND") && nt >= 2) {
        s->band = cvm_from_celsius(parse_float(tok[1]));
        send_fmt("OK BAND %.1f", cvm_to_celsius(s->band));
        return;
    }

    /* DISCONNECT <policy> */
    if (streqi(tok[0], "DISCONNECT") && nt >= 2) {
        if      (streqi(tok[1], "CONTINUE")) s->dc_policy = CVM_DC_CONTINUE;
        else if (streqi(tok[1], "PAUSE"))    s->dc_policy = CVM_DC_PAUSE;
        else if (streqi(tok[1], "STOP"))     s->dc_policy = CVM_DC_STOP;
        else if (streqi(tok[1], "ESTOP"))    s->dc_policy = CVM_DC_ESTOP;
        else { send_fmt("ERR BAD_POLICY"); return; }
        send_fmt("OK DISCONNECT %s", tok[1]);
        return;
    }

    /* PAUSE */
    if (streqi(tok[0], "PAUSE")) {
        if (s->mode == CVM_MODE_SEQUENCE) {
            s->vm_pause_elapsed = cvm_hal_millis() - s->vm_wait_start;
            cvm_hal_all_off();
            s->mode = CVM_MODE_PAUSED;
        }
        send_fmt("OK PAUSE");
        return;
    }

    /* RESUME */
    if (streqi(tok[0], "RESUME")) {
        if (s->mode == CVM_MODE_PAUSED) {
            s->mode = CVM_MODE_SEQUENCE;
            if (s->vm_waiting) s->vm_wait_start = cvm_hal_millis() - s->vm_pause_elapsed;
        }
        send_fmt("OK RESUME");
        return;
    }

    /* PROGRAM CLEAR/ADD/RUN/STOP/NEXT/PAUSE/RESUME/LIST */
    if (streqi(tok[0], "PROGRAM") && nt >= 2) {
        if (streqi(tok[1], "CLEAR")) {
            s->prog_len = 0;
            send_fmt("OK PROGRAM_CLEAR");
        }
        else if (streqi(tok[1], "ADD") && nt >= 3) {
            /* Reconstruct the instruction line from remaining tokens */
            char line[CVM_MSG_BUF];
            int pos = 0;
            for (int i = 2; i < nt && pos < CVM_MSG_BUF - CVM_NAME_LEN; i++) {
                if (i > 2) line[pos++] = ' ';
                int len = strlen(tok[i]);
                memcpy(line + pos, tok[i], len);
                pos += len;
            }
            line[pos] = '\0';
            parse_program_add(s, line);
        }
        else if (streqi(tok[1], "RUN")) {
            if (s->prog_len > 0) {
                vm_reset(s);
                s->band = s->config.hold_band;
                s->target = CVM_TARGET_OFF;
                s->hold_active = false;
                s->mode = CVM_MODE_SEQUENCE;
                send_fmt("OK PROGRAM_RUN %d", s->prog_len);
            } else {
                send_fmt("ERR PROGRAM_EMPTY");
            }
        }
        else if (streqi(tok[1], "STOP")) {
            cvm_hal_all_off();
            s->target = CVM_TARGET_OFF;
            s->hold_active = false;
            s->prompt_waiting = false;
            s->mode = CVM_MODE_IDLE;
            send_fmt("OK PROGRAM_STOP");
        }
        else if (streqi(tok[1], "NEXT")) {
            vm_force_next = true;
            send_fmt("OK PROGRAM_NEXT");
        }
        else if (streqi(tok[1], "PAUSE")) {
            if (s->mode == CVM_MODE_SEQUENCE) {
                s->vm_pause_elapsed = cvm_hal_millis() - s->vm_wait_start;
                cvm_hal_all_off();
                s->mode = CVM_MODE_PAUSED;
            }
            send_fmt("OK PAUSE");
        }
        else if (streqi(tok[1], "RESUME")) {
            if (s->mode == CVM_MODE_PAUSED) {
                s->mode = CVM_MODE_SEQUENCE;
                if (s->vm_waiting) s->vm_wait_start = cvm_hal_millis() - s->vm_pause_elapsed;
            }
            send_fmt("OK RESUME");
        }
        else if (streqi(tok[1], "LIST")) {
            for (int i = 0; i < s->prog_len; i++) {
                send_fmt("[%d] %s", i, cvm_opcode_name(s->program[i].op));
            }
            if (s->prog_len == 0) cvm_hal_send("PROGRAM (empty)");
        }
        return;
    }

    /* CONFIG / CONFIG SAVE */
    if (streqi(tok[0], "CONFIG")) {
        if (nt >= 2 && streqi(tok[1], "SAVE")) {
            cvm_save_config(s);
            send_fmt("OK CONFIG_SAVED");
        } else {
            send_fmt("CONFIG band=%ld hb_timeout=%lu prop_band=%ld antic=%ld cycle=%d",
                (long)s->config.hold_band,
                (unsigned long)s->config.heartbeat_timeout_ms,
                (long)s->config.tuning.prop_band,
                (long)s->config.tuning.anticipation_ms,
                s->config.tuning.cycle_ms);
        }
        return;
    }

    /* SET <actuator> <value> (direct mode) */
    if (streqi(tok[0], "SET") && nt >= 3) {
        if (s->mode != CVM_MODE_DIRECT) { send_fmt("ERR NOT_DIRECT"); return; }
        int ai = cvm_find_actuator(s, tok[1]);
        if (ai < 0) { send_fmt("ERR BAD_ACTUATOR %s", tok[1]); return; }
        int32_t v = parse_int(tok[2]);
        cvm_hal_set_actuator(ai, v);
        s->actuators[ai].current = v;
        send_fmt("OK SET %s %ld", tok[1], (long)v);
        return;
    }

    send_fmt("ERR UNKNOWN '%s'", command);
}


/* ═══════════════════════════════════════
   CONNECTION EVENTS
   ═══════════════════════════════════════ */

void cvm_on_connect(cvm_state_t* s) {
    s->connected = true;
    s->last_heartbeat = cvm_hal_millis();
    send_fmt("COOKVM 2.0 mode=%s", cvm_mode_name(s->mode));
}

void cvm_on_disconnect(cvm_state_t* s) {
    s->connected = false;

    if (s->mode == CVM_MODE_DIRECT) {
        cvm_estop(s);
        return;
    }

    if (s->mode == CVM_MODE_SEQUENCE) {
        switch (s->dc_policy) {
            case CVM_DC_CONTINUE:
                break;
            case CVM_DC_PAUSE:
                s->vm_pause_elapsed = cvm_hal_millis() - s->vm_wait_start;
                cvm_hal_all_off();
                s->mode = CVM_MODE_PAUSED;
                break;
            case CVM_DC_STOP:
                cvm_hal_all_off();
                s->target = CVM_TARGET_OFF;
                s->hold_active = false;
                s->mode = CVM_MODE_IDLE;
                break;
            case CVM_DC_ESTOP:
                cvm_estop(s);
                break;
        }
    }
}

void cvm_estop(cvm_state_t* s) {
    cvm_hal_all_off();
    s->mode = CVM_MODE_ESTOP;
    s->target = CVM_TARGET_OFF;
    s->hold_active = false;
    s->prompt_waiting = false;
    for (uint8_t i = 0; i < s->num_actuators; i++) s->actuators[i].current = 0;
    strncpy(s->fault_reason, "ESTOP", sizeof(s->fault_reason) - 1);
}


/* ═══════════════════════════════════════
   TELEMETRY
   ═══════════════════════════════════════ */

void cvm_broadcast_status(cvm_state_t* s) {
    /* v2.0 STATUS format:
     * Core fields first (survive BLE MTU truncation):
     *   mode, pc, wait, fault, up
     * Then dynamic sensor/actuator fields using declared names.
     * Then machine-specific custom instruction state.
     */
    char buf[CVM_MSG_BUF];
    int pos = 0;

    /* Core fields FIRST — never truncated */
    pos += snprintf(buf + pos, sizeof(buf) - pos,
        "STATUS mode=%s pc=%d wait=%d",
        cvm_mode_name(s->mode), s->vm_pc,
        (s->vm_waiting || s->prompt_waiting) ? 1 : 0);

    /* Fault */
    pos += snprintf(buf + pos, sizeof(buf) - pos,
        " fault=%s",
        strlen(s->fault_reason) ? s->fault_reason : "NONE");

    /* Uptime */
    pos += snprintf(buf + pos, sizeof(buf) - pos,
        " up=%lu", (unsigned long)(s->uptime / 1000));

    /* Dynamic sensor fields (names match CAPABILITY declarations) */
    for (uint8_t i = 0; i < s->num_sensors; i++) {
        cvm_sensor_t* se = &s->sensors[i];
        pos += snprintf(buf + pos, sizeof(buf) - pos, " %s=%.1f",
            se->name, cvm_to_celsius(se->filtered));
    }

    /* Dynamic actuator fields */
    for (uint8_t i = 0; i < s->num_actuators; i++) {
        pos += snprintf(buf + pos, sizeof(buf) - pos, " %s=%ld",
            s->actuators[i].name, (long)s->actuators[i].current);
    }

    /* Machine-specific: HOLD custom instruction state */
    if (s->hold_active) {
        pos += snprintf(buf + pos, sizeof(buf) - pos,
            " hold_active=1 hold_target=%.1f hold_sensor=%s duty=%ld",
            cvm_to_celsius(s->target),
            s->control_sensor < s->num_sensors
                ? s->sensors[s->control_sensor].name : "none",
            (long)(s->heater_duty / 100));
    } else {
        pos += snprintf(buf + pos, sizeof(buf) - pos, " hold_active=0");
    }

    /* Delta-T (dual-sensor machines) */
    if (s->num_sensors >= 2) {
        pos += snprintf(buf + pos, sizeof(buf) - pos,
            " dT=%.1f", cvm_to_celsius(s->delta_t));
    }

    cvm_hal_send(buf);
}