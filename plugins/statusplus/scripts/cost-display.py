#!/usr/bin/env python3
"""Statusline helper: lifetime-per-session cost, resettable on /clear.

Delta-accumulator model. Per session id we keep one JSON state file:

  ~/.claude/.session_cost/<sid>.json   {"prev_live": <float>, "total": <float>}

Each render, live = cost.total_cost_usd (CC's running total for the current
process) and:

  live >= prev_live          -> total += live - prev_live     (normal growth)
  live <  prev_live * 0.5    -> total += live                 (process restart)
  otherwise                  -> total += 0, keep prev_live    (out-of-order render)

- Restart: /resume reuses the sid but starts a new process whose live restarts
  near 0, so the accumulated total simply keeps growing from the sid's OWN
  prior state. No cross-session lookup, so cost can never leak between the
  many concurrent sessions a user may run in one project.
- The 0.5 fraction distinguishes a genuine restart (live collapses to ~0) from
  an out-of-order/overlapping render whose live is a hair below prev_live;
  treating the latter as a restart would re-add the whole prior total. On the
  out-of-order branch prev_live is deliberately NOT updated, so the stale
  value can't be double-counted when the newer total shows up again.

/clear resets the cost to $0. /clear mints a brand-new sid, so the
SessionStart hook (clear-cost-baseline.py) drops a one-shot marker
.session_cost_reset/<sid>; on that sid's first render we set total = 0 and
prev_live = live (live continues across /clear within the same process), then
consume the marker. This needs no prior-session lookup (CC's hook payload
exposes no parent/resumed-from session id -- see anthropics/claude-code#12235).
If a render for the new sid lands before the hook has written the marker, that
one render flashes the pre-clear total; the next render consumes the marker
and zeroes it. The reset check runs BEFORE the delta step so that resuming a
cleared-but-never-rendered session still starts at $0.

Migration: earlier plugin versions kept plain-float files
.session_cost/<sid> (last live) and .session_cost_displayed/<sid> (last
displayed figure). When no JSON state exists yet, those seed prev_live/total
so an in-flight session keeps its figure across the update. The legacy files
(including .session_cost_baseline/ and .session_cost_carry/) are left to age
out via the hook's 30-day prune.

The state file is rewritten atomically (temp file + os.replace) on every
render, which both prevents a concurrent same-sid reader from seeing a
truncated file and keeps the mtime fresh so the prune never eats a live
session's state.

This script runs on every statusline render: any unexpected error falls back
to printing the raw live value (or nothing) -- it must never break the
statusline.
"""
import json
import os
import pathlib
import sys
import tempfile


def read_legacy_float(path):
    """Best-effort read of an old-format plain-float state file."""
    try:
        return float(path.read_text().strip())
    except Exception:
        return None


def load_state(state_file, legacy_dir, sid):
    """Return (prev_live, total), seeding from pre-JSON state files if needed."""
    try:
        s = json.loads(state_file.read_text())
        prev_live, total = float(s['prev_live']), float(s['total'])
        if prev_live == prev_live and total == total:  # NaN guard
            return max(0.0, prev_live), max(0.0, total)
    except Exception:
        pass
    # One-time migration from the pre-1.7.0 multi-file layout (same sid only).
    legacy_live = read_legacy_float(legacy_dir / '.session_cost' / sid)
    legacy_displayed = read_legacy_float(legacy_dir / '.session_cost_displayed' / sid)
    if legacy_live is not None and legacy_displayed is not None:
        return max(0.0, legacy_live), max(0.0, legacy_displayed)
    return 0.0, 0.0


def save_state(state_file, prev_live, total):
    state_file.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(state_file.parent), prefix='.tmp-')
    try:
        with os.fdopen(fd, 'w') as f:
            json.dump({'prev_live': prev_live, 'total': total}, f)
        os.replace(tmp, str(state_file))
    except Exception:
        try:
            os.unlink(tmp)
        except Exception:
            pass


def compute(live, sid):
    claude_dir = pathlib.Path(os.path.expanduser('~')) / '.claude'
    state_file = claude_dir / '.session_cost' / (sid + '.json')
    reset_file = claude_dir / '.session_cost_reset' / sid

    prev_live, total = load_state(state_file, claude_dir, sid)

    if reset_file.exists():
        # /clear: start counting from the current live; drop any prior total.
        total = 0.0
        prev_live = live
        try:
            reset_file.unlink()
        except Exception:
            pass

    if live >= prev_live:
        total += live - prev_live
        prev_live = live
    elif live < prev_live * 0.5:
        # Process restart (/resume): live collapsed toward 0, count it fresh.
        total += live
        prev_live = live
    # else: out-of-order render -- ignore it, keep prev_live as the high-water
    # mark so the already-counted cost isn't re-added on the next render.

    save_state(state_file, prev_live, total)
    return total


def main():
    try:
        d = json.load(sys.stdin)
    except Exception:
        return
    if not isinstance(d, dict):
        return
    cost = d.get('cost')
    live = cost.get('total_cost_usd') if isinstance(cost, dict) else None
    try:
        live = float(live)
    except (TypeError, ValueError):
        return
    if live != live or live < 0:  # NaN / negative: don't trust the payload
        return

    sid = str(d.get('session_id') or '').replace('/', '_').replace('\\', '_')
    if not sid or sid in ('.', '..'):
        print(f'{live:.2f}')
        return

    try:
        total = compute(live, sid)
    except Exception:
        total = live  # never break the statusline: fall back to the raw value
    print(f'{total:.2f}')


if __name__ == '__main__':
    main()
