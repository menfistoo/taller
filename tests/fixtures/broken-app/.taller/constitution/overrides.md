---
overrides:
  - rule: size.function-too-long
    scope: "long_module.py"
  - rule: size.duplicate-block
    reason: "Being split ticket by ticket."
    until: 2020-01-01
  - rule: security.missing-permission
    reason: "Internal only."
  - rule: brand.hardcoded-font
    reason: "The owner likes it."
---

Overrides with deliberate problems (spec 15.2): no reason, expired, targeting a
security rule, and targeting a rule the project declares non-suppressible.
