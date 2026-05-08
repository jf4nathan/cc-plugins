#!/usr/bin/env python3
"""Statusline helper: display session cost with /clear and /resume support.

  displayed = max(0, live - baseline) + carry

- live: cost.total_cost_usd (CC's running total for the current process).
- baseline: subtracted (set by /clear to the live value at clear time).
- carry: added (set on /resume to preserve the prior process's displayed cost).

A new CC process for an existing sid (i.e. /resume) starts live at 0. We
detect that with `live < prev_live` (the last live value we saw for this
sid). On detection we set carry = prev_displayed and clear baseline so
the new process's display picks up where the prior one left off.

State files (all under ~/.claude/):
  .session_cost/<sid>           last live value
  .session_cost_displayed/<sid> last displayed value (for resume carry)
  .session_cost_baseline/<sid>  subtractive (set by /clear hook)
  .session_cost_carry/<sid>     additive (set on /resume detection)
"""
import json
import os
import pathlib
import sys

try:
    d = json.load(sys.stdin)
except Exception:
    sys.exit(0)

live = d.get('cost', {}).get('total_cost_usd')
sid = (d.get('session_id', '') or '').replace('/', '_')
if live is None:
    sys.exit(0)

if not sid:
    print(f'{live:.2f}')
    sys.exit(0)

home = pathlib.Path(os.path.expanduser('~'))
cost_file      = home / '.claude' / '.session_cost' / sid
displayed_file = home / '.claude' / '.session_cost_displayed' / sid
baseline_file  = home / '.claude' / '.session_cost_baseline' / sid
carry_file     = home / '.claude' / '.session_cost_carry' / sid

def read_float(p):
    try:
        return float(p.read_text().strip() or '0') if p.exists() else 0.0
    except Exception:
        return 0.0

prev_live      = read_float(cost_file)
prev_displayed = read_float(displayed_file)
baseline       = read_float(baseline_file)
carry          = read_float(carry_file)

if live + 1e-9 < prev_live:
    carry = prev_displayed
    baseline = 0.0
    try:
        if baseline_file.exists():
            baseline_file.unlink()
    except Exception:
        pass
    carry_file.parent.mkdir(parents=True, exist_ok=True)
    try:
        carry_file.write_text(f'{carry}')
    except Exception:
        pass

if baseline > live + 1e-9:
    baseline = 0.0
    try:
        baseline_file.unlink()
    except Exception:
        pass

displayed = max(0.0, live - baseline) + carry

for p, val in ((cost_file, str(live)), (displayed_file, f'{displayed}')):
    p.parent.mkdir(parents=True, exist_ok=True)
    try:
        p.write_text(val)
    except Exception:
        pass

print(f'{displayed:.2f}')
