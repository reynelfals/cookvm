# Examples

- `capabilities/`: sample CAPABILITY blocks (a bread machine with heater, fan, paddle
  and two NTCs, and a pressure cooker).
- `programs/`: sample programs for the bread-machine capability. Lines starting with
  `#` are human comments. Strip them, then send each line as `PROGRAM ADD <line>`.

| Program | What it shows |
|---|---|
| `boiled_eggs.cvm` | HOLD + wait inside the band with timeout, timed cook, fan cooldown |
| `warm_hold.cvm` | low-temperature hold for a fixed time |
| `bake_to_probe.cvm` | bake on the chamber sensor until the food probe hits ~95 °C or a timeout |
| `gentle_whip.cvm` | DJNZ loop pulsing the motor, heater forced off |
| `pulse_fold.cvm` | short paddle pulses with long rests |
| `fan_cooldown.cvm` | WAIT_LE with timeout |
| `safe_heater_off.cvm` | recovery program to force the heater off |
| `yogurt_with_prompt.cvm` | PROMPT/ACK (only for machines/brains that can ACK) |

DJNZ/JMP targets are **0-indexed line numbers of the program as sent** (comments
removed). In `gentle_whip.cvm`, `DJNZ R0 3` jumps back to `SET motor 1`.

Run them all through the emulator:
`python -m unittest discover -s reference/python/tests -v`
