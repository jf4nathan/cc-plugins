#!/usr/bin/env bash
# Claude Code statusLine script - part of the statusline plugin.
# Called by settings.json "statusLine.command" after running /statusline:setup.

input=$(cat)
# Parse all fields in a single python pass, output as unit-separator-delimited values.
IFS=$'\x1f' read -r current_dir model_name ctx_pct effort session_id worktree over200k <<< "$(echo "$input" | python3 -c "
import sys, json
d = json.load(sys.stdin)
ctx = d.get('context_window',{}).get('used_percentage')
fields = [
    d.get('workspace',{}).get('current_dir','') or d.get('cwd',''),
    d.get('model',{}).get('display_name',''),
    str(int(ctx)) if ctx is not None else '',
    d.get('effort',{}).get('level','') or '',
    d.get('session_id','') or '',
    d.get('workspace',{}).get('git_worktree','') or '',
    '1' if d.get('exceeds_200k_tokens') else '',
]
print('\x1f'.join(fields))
" 2>/dev/null)"
ctx_pct_display="${ctx_pct:-?}"

COST_SCRIPT="$HOME/.claude/bin/cost-display.py"
session_cost=$(echo "$input" | python3 "$COST_SCRIPT" 2>/dev/null)
branch=$(cd "$current_dir" 2>/dev/null && git -c core.fsmonitor=false branch --show-current 2>/dev/null)

# Format a unix epoch as "M/D Day H:MM AM/PM" — portable across macOS (BSD) and Linux.
fmt_epoch() {
    python3 -c "
import datetime, sys
t = datetime.datetime.fromtimestamp(int(sys.argv[1]))
h = t.hour % 12 or 12
ampm = 'AM' if t.hour < 12 else 'PM'
print(f'{t.month}/{t.day} {t.strftime(\"%a\")} {h}:{t.minute:02d} {ampm}')
" "$1" 2>/dev/null
}

age=""
start_ts=""
if [ -n "$session_id" ]; then
    start_dir="$HOME/.claude/.session_starts"
    start_file="$start_dir/$session_id"
    [ -d "$start_dir" ] || mkdir -p "$start_dir" 2>/dev/null
    [ -f "$start_file" ] || date +%s > "$start_file"

    # Look up stop epoch by session_id first (written by write-stop-epoch.py),
    # fall back to PPID (legacy, or if session_id was empty at Stop time).
    stop_file="$HOME/.claude/.session_stops/$session_id"
    [ -f "$stop_file" ] || stop_file="$HOME/.claude/.session_stops/$PPID"
    if [ -f "$stop_file" ]; then
        ts_epoch=$(cat "$stop_file" 2>/dev/null)
    else
        ts_epoch=$(cat "$start_file" 2>/dev/null)
    fi
    if [ -n "$ts_epoch" ]; then
        delta=$(( $(date +%s) - ts_epoch ))
        if [ $delta -lt 60 ]; then
            age="${delta}s"
        elif [ $delta -lt 3600 ]; then
            age="$((delta / 60))min"
        else
            age="$((delta / 3600))h$(((delta % 3600) / 60))m"
        fi
        # Age color tiers:
        #   <5min  bold bright red (1;91) - prompt cache still warm
        #   <30min yellow          (33)   - still in your head
        #   <2h    green           (32)   - normal idle
        #   <8h    cyan            (36)   - same-day cold
        #   else   dim gray        (90)   - stale
        if [ $delta -lt 300 ]; then
            age_color="1;91"
        elif [ $delta -lt 1800 ]; then
            age_color="33"
        elif [ $delta -lt 7200 ]; then
            age_color="32"
        elif [ $delta -lt 28800 ]; then
            age_color="36"
        else
            age_color="90"
        fi
        start_ts=$(fmt_epoch "$ts_epoch")
    fi
fi

# Line 1: dir + worktree + branch + sf org
printf '\033[1m%s\033[0m' "$(basename "$current_dir")"
if [ -n "$worktree" ]; then
    printf '  \033[35m⌥%s\033[0m' "$worktree"
fi
if [ -n "$branch" ]; then
    printf '  [\033[36m%s\033[0m]' "$branch"
fi

sf_info=$(python3 -c "
import json, os, pathlib, sys

home = pathlib.Path(os.path.expanduser('~'))
cwd = sys.argv[1]
# 1. Read target-org from .sf/config.json (current dir or home).
target = ''
for p in (pathlib.Path(cwd) / '.sf' / 'config.json', home / '.sf' / 'config.json'):
    try:
        if p.is_file():
            target = (json.loads(p.read_text()).get('target-org') or '').strip()
            if target:
                break
    except Exception:
        pass
if not target:
    sys.exit(0)

# 2. Resolve alias -> username if applicable.
username = target
try:
    aliases = json.loads((home / '.sfdx' / 'alias.json').read_text()).get('orgs', {})
    if target in aliases:
        username = aliases[target]
except Exception:
    pass

# 3. Read ~/.sfdx/<username>.json for isSandbox; fall back to alias-name check.
is_prod = None
try:
    auth = json.loads((home / '.sfdx' / f'{username}.json').read_text())
    is_sb = auth.get('isSandbox')
    is_scratch = auth.get('isScratch')
    if is_sb is False and is_scratch is False:
        is_prod = True
    elif is_sb is True or is_scratch is True:
        is_prod = False
except Exception:
    pass

if is_prod is None:
    is_prod = 'prod' in target.lower()

print(f'{target}\t{1 if is_prod else 0}')
" "$current_dir" 2>/dev/null)
if [ -n "$sf_info" ]; then
    sf_org="${sf_info%%	*}"
    sf_is_prod="${sf_info##*	}"
    if [ "$sf_is_prod" = "1" ]; then c="31"; else c="33"; fi
    printf '  \xe2\x98\x81 \033[%sm%s\033[0m' "$c" "$sf_org"
fi
printf '\n'

# Line 2: model + effort + ctx + cost + start_ts + age
if [ -n "$model_name" ]; then
    printf '\033[33m%s\033[0m' "$model_name"
fi
if [ -n "$effort" ]; then
    printf '  \033[34m[%s]\033[0m' "$effort"
fi
# Context % - turns red past 80%, plus a warning when over 200k tokens
ctx_color="35"
if [ -n "$ctx_pct" ] && [ "$ctx_pct" -ge 80 ] 2>/dev/null; then ctx_color="1;31"; fi
printf '  \033[%smctx:%s%%\033[0m' "$ctx_color" "$ctx_pct_display"
[ -n "$over200k" ] && printf ' \033[1;31m⚠\033[0m'
if [ -n "$session_cost" ]; then
    printf '  \033[36mcost:$%s\033[0m' "$session_cost"
fi
printf '  \033[37m%s\033[0m' "${start_ts:-$(fmt_epoch "$(date +%s)")}"
if [ -n "$age" ]; then
    printf ' \033[%sm(%s ago)\033[0m' "${age_color:-90}" "$age"
fi
