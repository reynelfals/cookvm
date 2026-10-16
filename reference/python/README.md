# cookvm — reference Python library and emulator

Pure-Python (stdlib only, Python 3.10+) implementation of the brain side of CookVM 2.0:

- `Capability`: parse a `CAPABILITY` block and build an LLM instruction reference from it
- `StatusParser`: parse `STATUS`, `EVENT`, `PROMPT`, `OK`/`ERR` and other lines
- `Commands`: build well-formed controller command strings
- `ProgramBuilder` and `validate_ops`: build programs and check them against a capability
- `Emulator` and `emulate`: dry-run a program against a simple thermal model of the machine
- `load_spec` and `load_reference_card`: load the bundled spec text

The library has no transport code. Bring your own BLE, serial or TCP link.

```bash
pip install .                         # or just add src/ to PYTHONPATH
python -m unittest discover -s tests -v
```

```python
from cookvm import Capability, validate_ops, emulate
cap = Capability.from_lines(open("../../examples/capabilities/bread_machine.cap").read().splitlines())
ops = ["DISCONNECT STOP", "CEILING chamber 120", "HOLD food 100",
       "WAIT_GE food 90 1800", "WAIT 600", "HOLD_OFF", "SET heater 0", "HALT"]
assert validate_ops(ops, cap) == []
print(emulate(ops, cap, food_params={"liquid_ml": 1000, "food_type": "water"}).report())
```

The emulator is a coarse planning tool, not a physics model. It regulates `HOLD` with a
simple bang-bang loop. The reference firmware uses time-proportioning with anticipation,
so real curves will differ. It auto-ACKs `PROMPT` after 5 simulated seconds.
