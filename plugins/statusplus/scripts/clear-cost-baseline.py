#!/usr/bin/env python3
"""SessionStart hook: reset the statusline cost display to $0 on /clear.

Cost is lifetime-per-session: cost-display.py keeps a per-sid delta
accumulator (.session_cost/<sid>.json) that carries across /resume via the
session's OWN prior state -- no cross-session lookup -- and resets on /clear.

/clear mints a brand-new sid and Claude Code's SessionStart payload exposes no
parent/resumed-from session id and no cost field (see anthropics/claude-code
#12235), so this hook cannot compute anything directly. Instead it drops a
one-shot marker:

  .session_cost_reset/<sid>

On that sid's next render, cost-display.py zeroes its total and starts
counting from the current live value, then deletes the marker. This needs no
knowledge of any other session, so it cannot leak cost between concurrent
same-project sessions. (An earlier version carried the prior session's total
across /resume via the most-recently-modified transcript in the project dir;
that heuristic leaked cost between concurrent sessions and was removed.)

/resume is intentionally NOT handled here: cost-display.py detects the resumed
sid's live restart and keeps accumulating on its own prior total.

On every SessionStart this also prunes plugin-owned state files older than
30 days. The prune list still includes the retired pre-1.7.0 state dirs
(.session_cost_displayed/, .session_cost_baseline/, .session_cost_carry/) so
leftover files from older plugin versions age out.

Note: this hook does NOT sync ~/.claude/bin/{statusline.sh,cost-display.py}
from the plugin. Auto-sync was removed because it silently overwrote user
customizations (the README invites users to ask Claude to edit those scripts).
To pick up new plugin script versions, run /statusplus:statusplus-update.
"""
import json
import os
import pathlib
import sys
import time

try:
    d = json.load(sys.stdin)
except Exception:
    sys.exit(0)
if not isinstance(d, dict):
    sys.exit(0)

home = pathlib.Path(os.path.expanduser('~'))
event = d.get('hook_event_name') or ''
if event != 'SessionStart':
    sys.exit(0)

# Prune stale state files (>30 days), once per session.
cutoff = time.time() - 30 * 86400
for dirname in ('.session_stops', '.session_starts', '.session_cost',
                '.session_cost_displayed', '.session_cost_baseline',
                '.session_cost_carry', '.session_cost_reset'):
    state_dir = home / '.claude' / dirname
    if not state_dir.is_dir():
        continue
    for f in state_dir.iterdir():
        try:
            if f.is_file() and f.stat().st_mtime < cutoff:
                f.unlink()
        except Exception:
            pass

sid = str(d.get('session_id') or '').replace('/', '_').replace('\\', '_')
source = (d.get('source') or '')
if not sid or sid in ('.', '..') or source != 'clear':
    sys.exit(0)

# Drop a one-shot reset marker; cost-display.py zeroes the display on the next
# render and consumes it. No prior-session lookup, so no cross-session leak.
try:
    reset_dir = home / '.claude' / '.session_cost_reset'
    reset_dir.mkdir(parents=True, exist_ok=True)
    (reset_dir / sid).write_text('1')
except Exception:
    pass
