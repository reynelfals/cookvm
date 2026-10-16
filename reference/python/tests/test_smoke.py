# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 the CookVM authors
"""Smoke test: parse a CAPABILITY, validate sample programs, run them
through the emulator. Runs with `python -m unittest` or pytest."""

import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))  # works without installing

from cookvm import Capability, StatusParser, validate_ops, emulate  # noqa: E402

EXAMPLES = HERE.parent.parent.parent / "examples"


def load_program(path: Path) -> list[str]:
    ops = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            ops.append(line)
    return ops


def load_cap(name: str) -> Capability:
    return Capability.from_lines((EXAMPLES / "capabilities" / name).read_text().splitlines())


class SmokeTest(unittest.TestCase):
    def setUp(self):
        self.cap = load_cap("bread_machine.cap")

    def test_capability_parses(self):
        self.assertTrue(self.cap.ready)
        self.assertEqual(self.cap.version, "2.0")
        self.assertIn("food", self.cap.sensors)
        self.assertIn("heater", self.cap.actuators)
        self.assertIn("HOLD", self.cap.custom_instructions)
        self.assertEqual(self.cap.limits["chamber_max"], 160)

    def test_status_parses(self):
        s = StatusParser.parse_status(
            "STATUS mode=SEQUENCE pc=3 wait=1 fault=NONE up=342 chamber=101.2 "
            "food=88.4 heater=1 fan=0 motor=0 hold_active=1 hold_target=100.0",
            sensor_names=set(self.cap.sensors), actuator_names=set(self.cap.actuators))
        self.assertEqual(s.mode, "SEQUENCE")
        self.assertEqual(s.pc, 3)
        self.assertTrue(s.waiting)
        self.assertIsNone(s.fault)
        self.assertAlmostEqual(s.sensor_values["food"], 88.4)
        self.assertEqual(s.actuator_values["heater"], 1.0)
        self.assertEqual(s.custom_state["hold_active"], 1)

    def test_boiled_eggs_emulates(self):
        ops = load_program(EXAMPLES / "programs" / "boiled_eggs.cvm")
        self.assertEqual(validate_ops(ops, self.cap), [])
        r = emulate(ops, self.cap, food_params={"liquid_ml": 1000, "food_type": "eggs_in_water"})
        print("\n" + r.report())
        self.assertTrue(r.halted, r.report())
        self.assertTrue(r.success, r.report())
        self.assertIn("boiling", r.events)
        self.assertIn("ready", r.events)
        self.assertTrue(all(v == 0 for v in r.final_actuators.values()))

    def test_all_bread_machine_examples(self):
        for name in ["warm_hold", "bake_to_probe", "gentle_whip", "pulse_fold",
                     "fan_cooldown", "safe_heater_off", "yogurt_with_prompt"]:
            with self.subTest(program=name):
                ops = load_program(EXAMPLES / "programs" / f"{name}.cvm")
                self.assertEqual(validate_ops(ops, self.cap), [])
                r = emulate(ops, self.cap, max_sim_s=12 * 3600,
                            food_params={"liquid_ml": 1000, "food_type": "water"})
                self.assertTrue(r.halted, f"{name}: {r.report()}")
                self.assertEqual([p.message for p in r.problems if p.severity == "error"], [])

    def test_examples_fit_reference_firmware_token_limit(self):
        # libcvm splits tokens longer than 11 chars (CVM_NAME_LEN - 1).
        for path in sorted((EXAMPLES / "programs").glob("*.cvm")):
            for op in load_program(path):
                for tok in op.split():
                    self.assertLessEqual(len(tok), 11, f"{path.name}: {op!r}")

    def test_validator_catches_bad_program(self):
        errs = validate_ops(["SET blender 1", "WAIT_GE probe 50", "JMP 99"], self.cap)
        self.assertTrue(any("blender" in e for e in errs))
        self.assertTrue(any("probe" in e for e in errs))
        self.assertTrue(any("out of range" in e for e in errs))
        self.assertTrue(any("HALT" in e for e in errs))


if __name__ == "__main__":
    unittest.main(verbosity=2)
