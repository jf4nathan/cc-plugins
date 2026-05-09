#!/usr/bin/env python3
"""Stop hook: record last-response epoch, keyed by session_id.

Wired as the Stop hook in hooks.json. Pruning of stale state files happens
once per session in clear-cost-baseline.py (SessionStart), not here.
"""
import json
import os
import pathlib
import sys
import time

try:
    data = json.load(sys.stdin)
except Exception:
    data = {}

sid = (data.get('session_id') or '').strip().replace('/', '_')
if not sid:
    sys.exit(0)

stop_dir = pathlib.Path(os.path.expanduser('~')) / '.claude' / '.session_stops'
stop_dir.mkdir(parents=True, exist_ok=True)
(stop_dir / sid).write_text(str(int(time.time())))
