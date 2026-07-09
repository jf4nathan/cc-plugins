---
name: statusplus-update
description: Sync the statusplus plugin's deployed scripts (~/.claude/bin/statusline.sh, cost-display.py, and llm-summary.py) with the current plugin version. Run this after a plugin update to pick up script changes. Detects user customizations and asks before overwriting them.
---

# Statusline Update

Re-deploy `statusline.sh`, `cost-display.py`, and `llm-summary.py` from the plugin to `~/.claude/bin/`. Use this after upgrading the plugin (e.g. `/plugin marketplace update cc-plugins`) to pick up new script behavior. Run again any time with `/statusplus:statusplus-update`.

## Why this is a separate skill

Earlier versions of the plugin auto-synced these files on every SessionStart, but that silently overwrote user customizations — and the README explicitly invites users to ask Claude to edit `~/.claude/bin/statusline.sh`. This skill makes the sync explicit and prompts before clobbering changes.

## Steps

Run all steps in order. Any non-trivial divergence between the deployed copy and the plugin copy must be surfaced to the user before overwriting.

### 1. Check what would change

For each of `statusline.sh`, `cost-display.py`, and `llm-summary.py`, determine whether the deployed file matches, is missing, or differs from the plugin's copy.

```bash
python3 - <<'PY'
import os, pathlib, hashlib

home = pathlib.Path(os.path.expanduser("~"))
plugin_scripts = pathlib.Path(os.environ["CLAUDE_PLUGIN_ROOT"]) / "scripts"
bin_dir = home / ".claude" / "bin"

def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None

statuses = {}
for name in ("statusline.sh", "cost-display.py", "llm-summary.py"):
    src, dst = plugin_scripts / name, bin_dir / name
    src_h, dst_h = sha(src), sha(dst)
    if dst_h is None:
        statuses[name] = "MISSING"
    elif src_h == dst_h:
        statuses[name] = "MATCH"
    else:
        statuses[name] = "DIFFER"

for k, v in statuses.items():
    print(f"{k}\t{v}")
PY
```

Parse the output. Three cases per file:

- `MATCH`: skip — nothing to do.
- `MISSING`: copy from plugin → bin (no prompt needed; nothing to lose).
- `DIFFER`: print the diff (next step) and ask before overwriting.

If all files are `MATCH`, tell the user "Already up to date." and stop.

### 2. Show the diff for any DIFFER file

For each `DIFFER` file, run:

```bash
diff -u "$HOME/.claude/bin/<name>" "${CLAUDE_PLUGIN_ROOT}/scripts/<name>"
```

Then present the user with a numbered choice (one per `DIFFER` file):

> The deployed `~/.claude/bin/statusline.sh` differs from the plugin's version. Diff above. The deployed copy may have user customizations.
>
> 1. Replace with the plugin's version (a timestamped backup will be saved next to it)
> 2. Keep the deployed version (skip this file)

If multiple files differ, ask separately for each so the user can keep customizations in one and update the other.

### 3. Apply the user's choices

For each file the user chose to replace (and any `MISSING` file):

```bash
python3 - <<'PY'
import os, pathlib, shutil, datetime, sys

home = pathlib.Path(os.path.expanduser("~"))
plugin_scripts = pathlib.Path(os.environ["CLAUDE_PLUGIN_ROOT"]) / "scripts"
bin_dir = home / ".claude" / "bin"
bin_dir.mkdir(parents=True, exist_ok=True)

# Pass the names to update as space-separated CLI args.
to_update = sys.argv[1:]
ts = datetime.datetime.now().strftime("%Y%m%d%H%M%S")

for name in to_update:
    src = plugin_scripts / name
    dst = bin_dir / name
    if dst.exists():
        backup = dst.with_suffix(dst.suffix + f".bak.{ts}")
        shutil.copy2(dst, backup)
        print(f"Backed up {dst} -> {backup}")
    shutil.copy2(src, dst)
    dst.chmod(0o755)
    print(f"Updated {dst}")
PY
```

Pass the file names the user approved (and any `MISSING` files) as positional args.

### 4. Patch config.json with any missing fields

If `~/.claude/.statusplus/config.json` exists, migrate it to current defaults. Adds missing fields, upgrades the stale `max_tokens: 30` default to `50`, and removes the deprecated `head_messages` and `tail_messages` keys. Unknown keys are preserved unchanged.

```bash
python3 - <<'PY'
import json, os, pathlib

p = pathlib.Path(os.path.expanduser("~/.claude/.statusplus/config.json"))
if not p.exists():
    print("NO_CONFIG")
else:
    config = json.loads(p.read_text(encoding='utf-8'))
    defaults = {
        "max_tokens": 50,
        "timeout_s": 8,
        "cache_ttl_s": 60,
    }
    for key, value in defaults.items():
        config.setdefault(key, value)
    if config.get("max_tokens") == 30:
        config["max_tokens"] = 50
    config.pop('head_messages', None)
    config.pop('tail_messages', None)
    p.write_text(json.dumps(config, indent=2) + "\n", encoding='utf-8')
    print("CONFIG_MIGRATED")
PY
```

- `CONFIG_MIGRATED`: config was written (idempotent — safe to re-run).
- `NO_CONFIG`: skip silently — they haven't configured the LLM headline.

### 5. Tell the user the result

Summarize what was updated, what was kept, and where backups went. If anything was updated, remind them: "Restart Claude Code to pick up the changes."

## Reverting

Each replaced file leaves a `*.bak.YYYYMMDDHHMMSS` next to it. To restore:

```bash
ls -t ~/.claude/bin/statusline.sh.bak.* | head -1 | xargs -I{} cp {} ~/.claude/bin/statusline.sh
```
