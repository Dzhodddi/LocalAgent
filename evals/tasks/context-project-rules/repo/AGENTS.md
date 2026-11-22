# Billing service

- Money is always `decimal.Decimal`, never float. Round money to cents with
  `ROUND_HALF_UP` (use the `CENTS` constant in billing.py).
- Every change gets one line in CHANGELOG.md under `## Unreleased`, starting with `- `
  and naming the function you added or changed.
- Tests: `python -m pytest -q`
