# Contributing to CookVM

Thanks for helping. CookVM is small on purpose. Changes should keep it simple enough to
run on a microcontroller and to be written by a person or an LLM.

## Ways to help
- **Ports.** Retrofit an appliance and share its HAL, its CAPABILITY block and what you
  learned (especially safety findings). Please add sample programs under `examples/`.
- **Spec feedback.** Open an issue that cites the section (for example "§5.2") and gives
  a concrete program or trace that shows the problem. See `spec/CHANGELOG.md` → "Open issues".
- **Reference code.** Fix bugs in `reference/python` or `firmware/libcvm`. The known
  issues list in `firmware/libcvm/README.md` is a good place to start.

## Ground rules
- **Safety first.** Never submit code that lets software bypass hard limits, clear
  faults without `CLEAR`, or drive loads from simulated sensors. Changes to safety
  behaviour need a test and a clear description.
- **Spec changes** need an update to `spec/CookVM_Spec_v2_0.md` *and* a
  `spec/CHANGELOG.md` entry. Keep new behaviour backward compatible where you can,
  or put it behind `FEATURES`/`INST`.
- **Tests.** `python -m unittest discover -s reference/python/tests -v` must pass. Add or
  extend tests for new behaviour. New example programs are run automatically.
- **Style.** Python 3.10+, stdlib only for the reference package. C99, no dynamic
  allocation, and all hardware access through `cvm_hal.h` for libcvm.
- **Licensing.** By contributing you agree that your contributions are licensed under the
  Apache License 2.0 (see `LICENSE`). New source files should carry
  `SPDX-License-Identifier: Apache-2.0`. Don't add third-party code without its
  license and attribution.
- **No personal data.** Keep IP addresses, hostnames, device MACs, keys, tokens and
  personal names out of code, logs and examples.

## Commit and PR checklist
- [ ] Tests pass locally
- [ ] Docs, spec and changelog updated if behaviour changed
- [ ] No secrets or personal or network identifiers
- [ ] Safety implications described in the PR
