#!/usr/bin/env bash
# Claude Code statusLine script - part of the statusplus plugin.
# Called by settings.json "statusLine.command" after running /statusplus:statusplus-setup.

input=$(cat)
# Parse all fields in a single python pass, output as unit-separator-delimited values.
IFS=$'\x1f' read -r current_dir model_name ctx_pct effort session_id worktree over200k used_tokens <<< "$(echo "$input" | python3 -c "
import sys, json, re
d = json.load(sys.stdin)
ctx = d.get('context_window',{})
ctx_pct = ctx.get('used_percentage')
raw = d.get('model',{}).get('display_name','') or ''
m = re.sub(r'^[Cc]laude[- ]', '', raw)
if re.match(r'^[a-z]+-\d', m):
    parts = m.split('-')
    m = parts[0].title() + ' ' + '.'.join(parts[1:])
m = re.sub(r'\s*\((\d+[kKmM])\s+context\)', r' \1', m)
fields = [
    d.get('workspace',{}).get('current_dir','') or d.get('cwd',''),
    m.strip(),
    str(int(ctx_pct)) if ctx_pct is not None else '',
    d.get('effort',{}).get('level','') or '',
    d.get('session_id','') or '',
    d.get('workspace',{}).get('git_worktree','') or '',
    '1' if d.get('exceeds_200k_tokens') else '',
    str(int(ctx.get('used_tokens',0))),
]
print('\x1f'.join(fields))
" 2>/dev/null)"
ctx_pct_display="${ctx_pct:-?}"

case "$effort" in
    low)    effort="lo"  ;;
    medium) effort="med" ;;
    high)   effort="hi"  ;;
    xhigh)  effort="xhi" ;;
esac


COST_SCRIPT="$HOME/.claude/bin/cost-display.py"
session_cost=$(echo "$input" | python3 "$COST_SCRIPT" 2>/dev/null)

# Run a git command with a 3s wall-clock timeout if `timeout` is available
# (coreutils). Falls back to bare git otherwise. Returns git's stdout or
# empty on timeout/error. All callers pass `-c core.fsmonitor=false` to
# avoid waiting on an unresponsive fsmonitor daemon.
git_with_timeout() {
    if command -v timeout >/dev/null 2>&1; then
        timeout 3 git "$@"
    else
        git "$@"
    fi
}

# Compact git status segment for line 1: "+A/-R/++N (U)".
#   +A/-R  added/removed lines vs HEAD (numstat sum)
#   ++N    lines in untracked files (xargs wc -l)
#   (U)    unpushed commits ahead of @{upstream}
# Each segment renders only when non-zero. Returns empty on no-git, no
# upstream, or all-zero state -- caller decides whether to print.
git_status() {
    local dir="$1"
    [ -z "$dir" ] && return
    local diff added removed untracked unpushed out
    diff=$(git_with_timeout -C "$dir" -c core.fsmonitor=false diff --numstat HEAD 2>/dev/null)
    added=$(awk '{a+=$1} END{print a+0}' <<<"$diff")
    removed=$(awk '{r+=$2} END{print r+0}' <<<"$diff")
    untracked=$(cd "$dir" 2>/dev/null && git_with_timeout -c core.fsmonitor=false ls-files --others --exclude-standard 2>/dev/null | xargs wc -l 2>/dev/null | tail -1 | awk '{print $1+0}')
    unpushed=$(git_with_timeout -C "$dir" -c core.fsmonitor=false rev-list --count @{upstream}..HEAD 2>/dev/null)
    out=""
    if [ "${added:-0}" -gt 0 ] || [ "${removed:-0}" -gt 0 ]; then
        out="+${added}/-${removed}"
    fi
    if [ "${untracked:-0}" -gt 0 ]; then
        [ -n "$out" ] && out="${out}/++${untracked}" || out="++${untracked}"
    fi
    if [ -n "$unpushed" ] && [ "$unpushed" -gt 0 ] 2>/dev/null; then
        [ -n "$out" ] && out="${out} (${unpushed})" || out="(${unpushed})"
    fi
    echo "$out"
}

branch=$(cd "$current_dir" 2>/dev/null && git_with_timeout -c core.fsmonitor=false branch --show-current 2>/dev/null)

# Format a unix epoch as "M/D Day H:MM AM/PM" — portable across macOS (BSD) and Linux.
fmt_epoch() {
    python3 -c "
import datetime, sys
t = datetime.datetime.fromtimestamp(int(sys.argv[1]))
h = t.hour % 12 or 12
ampm = 'AM' if t.hour < 12 else 'PM'
print(f'{t.month}/{t.day} {h}:{t.minute:02d} {ampm}')
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
            age="$((delta / 60))m"
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

# Detect terminal width. Claude Code runs the statusline with stdin piped, so the
# script has no controlling TTY of its own — `tput cols` returns 80 and `/dev/tty`
# is "not a tty". Walk up the parent process chain to find a TTY and read its size.
# Claude Code drops any statusline row whose visible width exceeds the render area,
# so we truncate to fit and keep the leftmost (most useful) content visible.
term_cols=""
pid=$$
for _ in 1 2 3 4 5 6 7 8; do
    ppid=$(ps -o ppid= -p "$pid" 2>/dev/null | tr -d ' ')
    if [ -z "$ppid" ] || [ "$ppid" = "0" ] || [ "$ppid" = "1" ]; then
        break
    fi
    tty=$(ps -o tty= -p "$ppid" 2>/dev/null | tr -d ' ')
    if [ -n "$tty" ] && [ "$tty" != "??" ] && [ -e "/dev/$tty" ]; then
        term_cols=$(stty size <"/dev/$tty" 2>/dev/null | awk '{print $2}')
        if [ -n "$term_cols" ] && [ "$term_cols" -gt 0 ] 2>/dev/null; then
            break
        fi
        term_cols=""
    fi
    pid=$ppid
done
[ -z "$term_cols" ] && term_cols="${COLUMNS:-120}"
# Claude Code's render area is narrower than the host TTY — it reserves columns for
# the input box border and right-side indicators. Empirically ~15 cols of chrome;
# anything wider than (term - 15) gets dropped entirely.
term_cols=$((term_cols - 15))
[ "$term_cols" -lt 20 ] 2>/dev/null && term_cols=20

# Line 1: dir + worktree + branch + sf org
# In a linked worktree, the harness's `git_worktree`, the cwd basename, and the
# branch often collapse to the same string. Surface the origin repo basename
# instead and dedupe `[branch]` when it matches the worktree name.
origin_basename=""
if [ -n "$worktree" ]; then
    common_dir=$(cd "$current_dir" 2>/dev/null && git -c core.fsmonitor=false rev-parse --path-format=absolute --git-common-dir 2>/dev/null)
    [ -n "$common_dir" ] && origin_basename=$(basename "$(dirname "$common_dir")")
fi

line1=""
if [ -n "$worktree" ] && [ -n "$origin_basename" ] && [ "$origin_basename" != "$worktree" ]; then
    line1+=$(printf '\033[1m%s\033[0m' "$origin_basename")
    line1+=$(printf '  \033[35m⌥%s\033[0m' "$worktree")
    if [ -n "$branch" ] && [ "$branch" != "$worktree" ]; then
        line1+=$(printf '  [\033[36m%s\033[0m]' "$branch")
    fi
else
    line1+=$(printf '\033[1m%s\033[0m' "$(basename "$current_dir")")
    if [ -n "$worktree" ]; then
        line1+=$(printf '  \033[35m⌥%s\033[0m' "$worktree")
    fi
    if [ -n "$branch" ]; then
        line1+=$(printf '  [\033[36m%s\033[0m]' "$branch")
    fi
fi

# Compact git status: "+A/-R/++N (U)". Silent when no-git or all-zero.
if [ -n "$branch" ]; then
    git_st=$(git_status "$current_dir")
    [ -n "$git_st" ] && line1+=$(printf '  \033[90m%s\033[0m' "$git_st")
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
    line1+=$(printf '  \xe2\x98\x81 \033[%sm%s\033[0m' "$c" "$sf_org")
fi

# Line 2: model + effort + ctx + cost + start_ts + age
line2=""
if [ -n "$model_name" ]; then
    line2+=$(printf '\033[34m%s\033[0m' "$model_name")
fi
if [ -n "$effort" ]; then
    line2+=$(printf '  \033[34m[%s]\033[0m' "$effort")
fi
ctx_bar=$(python3 -c "
pct = int('${ctx_pct}') if '${ctx_pct}'.isdigit() else 0
tokens = int('${used_tokens}') if '${used_tokens}'.isdigit() else 0
width = 12
filled = round(width * pct / 100)
bar = '▓' * filled + '▒' * (width - filled)
if tokens >= 400000 or pct >= 80:
    color = '1;31'
elif tokens >= 200000:
    color = '33'
else:
    color = '35'
print(f'\033[{color}m{bar} {pct}%\033[0m')
" 2>/dev/null)
line2+="  ${ctx_bar:-ctx:${ctx_pct_display}%}"
if [ -n "$session_cost" ]; then
    line2+=$(printf '  \033[36m$%s\033[0m' "$session_cost")
fi
if [ -n "$age" ] && [ "${delta:-0}" -lt 86400 ]; then
    line2+=$(printf '  \033[%sm(%s)\033[0m' "${age_color:-90}" "$age")
elif [ -n "$start_ts" ]; then
    line2+=$(printf '  \033[%sm%s\033[0m' "${age_color:-90}" "$start_ts")
else
    line2+=$(printf '  \033[37m%s\033[0m' "$(fmt_epoch "$(date +%s)")")
fi

# Line 3: LLM-generated headline (optional, opt-in via /statusplus:statusplus-llm-setup).
# llm-summary.py prints the cached headline instantly and spawns a detached
# background refresh if stale. If not configured, it prints nothing and we
# stay at two lines.
line3=""
LLM_SCRIPT="$HOME/.claude/bin/llm-summary.py"
if [ -f "$LLM_SCRIPT" ]; then
    headline=$(echo "$input" | python3 "$LLM_SCRIPT" 2>/dev/null)
    if [ -n "$headline" ]; then
        line3=$(printf '\033[3;33m%s\033[0m' "$headline")
    fi
fi

# Truncate all lines to display width in a single python3 spawn.
# Counts terminal columns (wcwidth-aware) so wide chars like ⌥ ☁ ⚠ and emoji don't
# blow past term_cols and get the row dropped by Claude Code. Appends a dim "…"
# when content was cut so the user can tell something is hidden, plus a final
# reset so color state can't leak.
LINE1="$line1" LINE2="$line2" LINE3="$line3" COLS="$term_cols" python3 <<'PY'
import os, re, sys, unicodedata

ansi = re.compile(r"\x1b\[[0-9;]*m")

def width(ch):
    # Combining marks and zero-width joiners take no columns.
    if unicodedata.category(ch) in ("Mn", "Me", "Cf"):
        return 0
    if unicodedata.east_asian_width(ch) in ("W", "F"):
        return 2
    cp = ord(ch)
    # Common emoji / symbol ranges that render double-wide on most terminals
    # but are reported as "N" by east_asian_width.
    if (
        0x2600 <= cp <= 0x27BF       # misc symbols + dingbats (☁ ⚠)
        or 0x1F300 <= cp <= 0x1FAFF  # emoji
        or 0x2B00 <= cp <= 0x2BFF    # arrows / geometric (⌥ is 0x2325, handled below)
    ):
        return 2
    if cp == 0x2325:  # ⌥ option key
        return 1  # renders single in most monospace fonts
    return 1

def trunc(s, n):
    out, vis, i, cut = [], 0, 0, False
    while i < len(s):
        m = ansi.match(s, i)
        if m:
            out.append(m.group(0))
            i = m.end()
            continue
        ch = s[i]
        w = width(ch)
        if vis + w > n:
            cut = True
            break
        out.append(ch)
        vis += w
        i += 1
    if cut:
        out.append("\x1b[2m…\x1b[0m")
    out.append("\x1b[0m")
    return "".join(out)

n = int(os.environ["COLS"])
sys.stdout.write(trunc(os.environ["LINE1"], n))
sys.stdout.write("\n")
sys.stdout.write(trunc(os.environ["LINE2"], n))
line3 = os.environ.get("LINE3", "")
if line3:
    sys.stdout.write("\n")
    sys.stdout.write(trunc(line3, n))
PY
