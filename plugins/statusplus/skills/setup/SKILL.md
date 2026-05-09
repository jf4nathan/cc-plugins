---
name: setup
description: Fully install the statusplus plugin. Copies scripts to ~/.claude/bin/, writes the statusLine block into ~/.claude/settings.json, and tells the user to restart. Run once after installing the plugin.
---

# Statusline Setup

Complete the statusline install in one shot - no manual settings.json editing required.

## Steps

Run all three steps in order. Do not skip step 2.

### 1. Copy scripts to ~/.claude/bin/

```bash
mkdir -p "$HOME/.claude/bin"
cp "${CLAUDE_PLUGIN_ROOT}/scripts/statusline.sh" "$HOME/.claude/bin/statusline.sh"
cp "${CLAUDE_PLUGIN_ROOT}/scripts/cost-display.py" "$HOME/.claude/bin/cost-display.py"
chmod +x "$HOME/.claude/bin/statusline.sh"
echo "Scripts installed."
```

`statusline.sh` and `cost-display.py` are copied to `~/.claude/bin/` so they survive plugin updates without requiring a re-run of setup. The Stop/SessionStart/UserPromptSubmit hook scripts (`write-stop-epoch.py`, `clear-cost-baseline.py`) are invoked directly from the plugin root via `${CLAUDE_PLUGIN_ROOT}` in hooks.json, so they update automatically with the plugin.

### 2. Patch ~/.claude/settings.json with the statusLine block

This must be done programmatically. Do NOT print the block and ask the user to paste it.

**First, check for an existing `statusLine` config.** If one exists, do NOT overwrite silently — show the user what's currently there and ask for confirmation before replacing.

```bash
python3 - <<'PY'
import json, os, pathlib
p = pathlib.Path(os.path.expanduser("~/.claude/settings.json"))
if p.exists():
    try:
        d = json.loads(p.read_text())
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
> Replace it with the statusline plugin's config? A timestamped backup will be written either way.
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
        d = json.loads(p.read_text())
    except json.JSONDecodeError as e:
        print(f"ERROR: ~/.claude/settings.json is not valid JSON: {e}", file=sys.stderr)
        print(f"A backup was saved to {backup}.", file=sys.stderr)
        print("Fix the file (the statusplus plugin doesn't support comments or trailing commas) and re-run /statusplus:setup.", file=sys.stderr)
        sys.exit(2)
else:
    p.parent.mkdir(parents=True, exist_ok=True)
    d = {}
d["statusLine"] = {
    "type": "command",
    "command": 'bash "$HOME/.claude/bin/statusline.sh"',
    "refreshInterval": 30,
}
p.write_text(json.dumps(d, indent=2) + "\n")
print(f"statusLine block written to {p}")
PY
```

The write step:
- Backs up the existing `settings.json` with a timestamped `.bak.YYYYMMDDHHMMSS` suffix.
- Adds (or replaces) only the `statusLine` key, preserving all other settings.
- Creates the file if it doesn't exist.
- If `settings.json` is malformed (trailing comma, JSONC comments, etc.) the script prints a clear error pointing at the backup and exits non-zero — it does **not** overwrite the file with a default. If you see this error, fix the JSON and re-run `/statusplus:setup`.

### 3. Tell the user to restart

Tell them: "Restart Claude Code for the statusline to take effect. The plugin's hooks (Stop epoch writer, SessionStart/UserPromptSubmit cost baseline) are already active and need no further setup."

## What the statusline shows

**Line 1:** current directory (bold) + git branch (cyan) + Salesforce org (red=prod, yellow=other)

**Line 2:** model name + effort level + context % + session cost + timestamp + time since last response ("X ago")

The "ago" counter is color-coded by staleness:
- bold red - under 5 min (prompt cache still warm)
- yellow - 5-30 min
- green - 30 min to 2 hours
- cyan - 2-8 hours
- dim gray - over 8 hours

Cost display resets to $0 when you run `/clear`.

## Reverting

To remove the statusline, restore the most recent backup:

```bash
ls -t ~/.claude/settings.json.bak.* | head -1 | xargs -I{} cp {} ~/.claude/settings.json
```
