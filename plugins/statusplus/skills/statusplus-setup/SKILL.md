---
name: statusplus-setup
description: Fully install the statusline. Copies scripts to ~/.claude/bin/, writes the statusLine block into ~/.claude/settings.json, and tells the user to restart. Run once after installing the plugin.
---

# Statusline Setup

Complete the statusline install in one shot - no manual settings.json editing required.

## Steps

Run all three steps in order. Do not skip step 2.

### 1. Copy scripts to ~/.claude/bin/

> **Windows (Git Bash / WSL) note:** Before running the bash block below, confirm bash is on your PATH. In PowerShell: `(Get-Command bash).Source`. Use that path if the script can't find bash.

```bash
mkdir -p "$HOME/.claude/bin"
cp "${CLAUDE_PLUGIN_ROOT}/scripts/statusline.sh"   "$HOME/.claude/bin/statusline.sh"
cp "${CLAUDE_PLUGIN_ROOT}/scripts/cost-display.py" "$HOME/.claude/bin/cost-display.py"
cp "${CLAUDE_PLUGIN_ROOT}/scripts/llm-summary.py"  "$HOME/.claude/bin/llm-summary.py"
chmod +x "$HOME/.claude/bin/statusline.sh" 2>/dev/null || true
echo "Scripts installed."
```

`statusline.sh`, `cost-display.py`, and `llm-summary.py` are copied to `~/.claude/bin/` so they survive plugin updates without requiring a re-run of setup. (`llm-summary.py` is dormant until the user runs `/statusplus:statusplus-llm-setup` — its presence alone adds no behavior.) The Stop/SessionStart hook scripts (`write-stop-epoch.py`, `clear-cost-baseline.py`) are invoked directly from the plugin root via `${CLAUDE_PLUGIN_ROOT}` in hooks.json, so they update automatically with the plugin.

### 2. Patch ~/.claude/settings.json with the statusLine block

This must be done programmatically. Do NOT print the block and ask the user to paste it.

**First, check for an existing `statusLine` config.** If one exists, do NOT overwrite silently — show the user what's currently there and ask for confirmation before replacing.

```bash
python3 - <<'PY'
import json, os, pathlib
p = pathlib.Path(os.path.expanduser("~/.claude/settings.json"))
if p.exists():
    try:
        d = json.loads(p.read_text(encoding='utf-8'))
    except Exception:
        d = {}
    existing = d.get("statusLine")
    if existing:
        print("EXISTING_STATUSLINE_FOUND")
        print(json.dumps(existing, indent=2))
    else:
        print("NO_EXISTING_STATUSLINE")
else:
    print("NO_SETTINGS_FILE")
PY
```

If the output starts with `EXISTING_STATUSLINE_FOUND`, ask the user (a numbered choice):

> I found an existing `statusLine` config in `~/.claude/settings.json`:
> ```json
> { ...existing config... }
> ```
> Replace it with this plugin's config? A timestamped backup will be written either way.
> 1. Yes, replace it
> 2. No, leave it alone (cancel setup)

Only proceed to the write step if the user picks option 1, or if no existing config was found.

**Then run the write step:**

```bash
python3 - <<'PY'
import json, os, pathlib, shutil, datetime, sys
p = pathlib.Path(os.path.expanduser("~/.claude/settings.json"))
if p.exists():
    backup = p.with_suffix(p.suffix + ".bak." + datetime.datetime.now().strftime("%Y%m%d%H%M%S"))
    shutil.copy2(p, backup)
    try:
        d = json.loads(p.read_text(encoding='utf-8'))
    except json.JSONDecodeError as e:
        print(f"ERROR: ~/.claude/settings.json is not valid JSON: {e}", file=sys.stderr)
        print(f"A backup was saved to {backup}.", file=sys.stderr)
        print("Fix the file (the statusplus plugin doesn't support comments or trailing commas) and re-run /statusplus:statusplus-setup.", file=sys.stderr)
        sys.exit(2)
else:
    p.parent.mkdir(parents=True, exist_ok=True)
    d = {}
import platform, shutil
if platform.system() == "Windows":
    bash = (shutil.which("bash") or "bash").replace("\\", "/")
    cmd = f'{bash} "$HOME/.claude/bin/statusline.sh"'
else:
    cmd = 'bash "$HOME/.claude/bin/statusline.sh"'
d["statusLine"] = {
    "type": "command",
    "command": cmd,
    "refreshInterval": 30,
}
p.write_text(json.dumps(d, indent=2) + "\n", encoding='utf-8')
print(f"statusLine block written to {p}")
PY
```

The write step:
- Backs up the existing `settings.json` with a timestamped `.bak.YYYYMMDDHHMMSS` suffix.
- Adds (or replaces) only the `statusLine` key, preserving all other settings.
- Creates the file if it doesn't exist.
- If `settings.json` is malformed (trailing comma, JSONC comments, etc.) the script prints a clear error pointing at the backup and exits non-zero — it does **not** overwrite the file with a default. If you see this error, fix the JSON and re-run `/statusplus:statusplus-setup`.

### 3. Tell the user to restart

Tell them: "Restart Claude Code for the statusline to take effect. The plugin's hooks (Stop epoch writer, SessionStart cost baseline) are already active and need no further setup."

## What the statusline shows

**Line 1:** current directory (bold) + git branch (cyan) + Salesforce org (red=prod, yellow=other)

**Line 2:** model name + effort level + context % + session cost + timestamp + time since last response ("X ago")

The "ago" counter is color-coded by staleness:
- bold red - under 5 min (prompt cache still warm)
- yellow - 5-30 min
- green - 30 min to 2 hours
- cyan - 2-8 hours
- dim gray - over 8 hours

**Cost display rules:**
- Cost shown is the lifetime accumulated cost for the current session (not a snapshot).
- State lives in one atomic JSON accumulator per session — no partial reads.
- `/clear` creates a one-shot reset marker that is consumed by the next render; the display returns to $0.00 for the new session.
- `/resume` needs no cross-session transcript lookup or carry file — continuity is built into the accumulator.

## Reverting

To remove the statusline, restore the most recent backup:

```bash
ls -t ~/.claude/settings.json.bak.* | head -1 | xargs -I{} cp {} ~/.claude/settings.json
```
