#!/usr/bin/env python3
"""SessionStart hook: handle /clear and /resume so the statusline cost
behaves intuitively across both.

Display formula (in cost-display.py):
  displayed = max(0, live - baseline) + carry

This hook adjusts baseline (subtractive) and carry (additive) on
SessionStart events:

- source == 'clear': same CC process; live continues from before. We want
  displayed to drop to 0. Read the prior session's live cost from this
  project's transcript dir + .session_cost/<prior_sid>, and write it as
  baseline for the new sid.

- source == 'resume': new CC process; live restarts at 0. We want displayed
  to pick up where the prior session left off. Read the prior session's
  *displayed* cost from .session_cost_displayed/<prior_sid> and write it
  as carry for the new sid.

Prior sid is identified by the most-recently-modified .jsonl in the
project's transcript dir (~/.claude/projects/<slug>/) other than the new
sid. This scopes the lookup to THIS Claude Code instance's project, so
multiple concurrent instances in different cwds don't interfere.

On every SessionStart this also prunes plugin-owned state files older
than 30 days.

Note: this hook does NOT sync ~/.claude/bin/{statusline.sh,cost-display.py}
from the plugin. Auto-sync was removed because it silently overwrote user
customizations (the README invites users to ask Claude to edit those
scripts). To pick up new plugin script versions, run /statusline:update.
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

home = pathlib.Path(os.path.expanduser('~'))
event = d.get('hook_event_name') or ''
if event != 'SessionStart':
    sys.exit(0)

# Prune stale state files (>30 days), once per session.
cutoff = time.time() - 30 * 86400
for dirname in ('.session_stops', '.session_starts', '.session_cost',
                '.session_cost_displayed', '.session_cost_baseline',
                '.session_cost_carry'):
    state_dir = home / '.claude' / dirname
    if not state_dir.is_dir():
        continue
    for f in state_dir.iterdir():
        try:
            if f.is_file() and f.stat().st_mtime < cutoff:
                f.unlink()
        except Exception:
            pass

sid = (d.get('session_id', '') or '').replace('/', '_')
source = (d.get('source') or '')
if not sid or source not in ('clear', 'resume'):
    sys.exit(0)

# Find prior sid via this project's transcript dir.
prior_sid = None
transcript_path = d.get('transcript_path') or ''
if transcript_path:
    project_dir = pathlib.Path(transcript_path).parent
    if project_dir.is_dir():
        candidates = []
        for f in project_dir.iterdir():
            if not (f.is_file() and f.suffix == '.jsonl'):
                continue
            stem = f.stem
            if stem == sid:
                continue
            try:
                candidates.append((f.stat().st_mtime, stem))
            except Exception:
                pass
        if candidates:
            candidates.sort(reverse=True)
            prior_sid = candidates[0][1]

def read_str(p, default='0'):
    try:
        return p.read_text().strip() or default if p.exists() else default
    except Exception:
        return default

if source == 'clear':
    prior_live = '0'
    if prior_sid:
        prior_live = read_str(home / '.claude' / '.session_cost' / prior_sid)
    out_dir = home / '.claude' / '.session_cost_baseline'
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        (out_dir / sid).write_text(prior_live)
    except Exception:
        pass

elif source == 'resume':
    prior_displayed = '0'
    if prior_sid:
        prior_displayed = read_str(home / '.claude' / '.session_cost_displayed' / prior_sid)
    out_dir = home / '.claude' / '.session_cost_carry'
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        (out_dir / sid).write_text(prior_displayed)
    except Exception:
        pass
