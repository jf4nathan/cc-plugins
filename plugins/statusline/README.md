# statusline

A two-line Claude Code statusline that surfaces the things you actually want to know at a glance: where you are, what model you're on, how much context and money you've burned, and how long since Claude last replied.

## Install

Add the marketplace once, then install the plugin:

```
/plugin marketplace add jf4nathan/cc-plugins
/plugin install statusline@cc-plugins
/statusline:setup
```

Restart Claude Code. Done. The setup skill copies the scripts to `~/.claude/bin/`, writes the `statusLine` block into `~/.claude/settings.json` automatically (with a backup), and tells you to restart.

> **Already have a `statusLine` configured?** The setup skill detects an existing `statusLine` block and asks before replacing it. The previous config is always preserved in a timestamped `~/.claude/settings.json.bak.*` backup.

## What it looks like

In a regular repo:

```
my-project  [my-feature-branch]
Opus 4.7  [xhigh]  ctx:14%  cost:$1.27  5/8 Thu 9:12 AM (3min ago)
```

In a worktree (`git worktree add ../wt-feature feature-branch`):

```
my-project  ⌥wt-feature  [feature-branch]
Opus 4.7  [xhigh]  ctx:18%  cost:$2.41  5/8 Thu 11:04 AM (1min ago)
```

When you're getting close to the context limit (`ctx:` turns bold red ≥80%, plus a `⚠` once total tokens exceed 200k):

```
my-project  [my-feature-branch]
Opus 4.7  [xhigh]  ctx:87% ⚠  cost:$5.62  5/8 Thu 2:48 PM (12s ago)
```

## What's on the statusline

**Line 1 (location):**
- Current directory, bold
- `⌥worktree-name` if you're inside a `git worktree add` checkout (so you don't lose track of which worktree this terminal is in)
- `[branch]` in cyan when you're in a git repo

**Line 2 (session):**
- Model display name, yellow
- `[effort]` blue, when the model supports a reasoning effort level
- `ctx:NN%` purple, switches to bold red past 80%; adds `⚠` if total tokens exceed 200k
- `cost:$X.YZ` cyan, resets when you `/clear`, picks up where you left off after `/resume`
- Timestamp + `(N min ago)` since Claude last responded, color-coded:
  - bold red <5min (prompt cache still warm)
  - yellow <30min
  - green <2h
  - cyan <8h
  - dim gray after

## Customizing

Want a different layout, color scheme, or to add/remove fields? **The fastest way is to ask Claude.** Open a session and say something like:

- *"In `~/.claude/bin/statusline.sh`, change the branch color from cyan to magenta"*
- *"Add the API duration field (`cost.total_api_duration_ms`) to my statusline, formatted as seconds"*
- *"Hide the 'ago' timestamp on line 2"*
- *"Show vim mode when `vim.mode` is set"*
- *"Make the time format 24-hour instead of 12-hour"*

The script is plain bash + python and is already documented inline. Claude can read it, make the change, and you just restart Claude Code to see the result.

> **Picking up plugin updates.** The plugin's bundled scripts are *copied* into `~/.claude/bin/` at install time, so customizations there are yours and won't be overwritten. After `/plugin marketplace update cc-plugins` (or any plugin upgrade), run `/statusline:update` to sync the deployed copies with the plugin's latest. The skill detects local edits and asks before replacing them — so you can keep your customizations and update only the files you haven't touched.

### Available data fields

The statusline script receives the full Claude Code session JSON on stdin. The most useful fields:

| Field | Purpose |
|-------|---------|
| `model.display_name`, `model.id` | Model name |
| `workspace.current_dir`, `cwd` | Current dir |
| `workspace.git_worktree` | Worktree name (if in one) |
| `session_name` | Custom name from `/rename` |
| `context_window.used_percentage` | Context % used |
| `exceeds_200k_tokens` | Past 200k token threshold |
| `cost.total_cost_usd` | Session cost |
| `cost.total_lines_added`, `total_lines_removed` | Lines changed |
| `cost.total_duration_ms`, `total_api_duration_ms` | Wall-clock vs API time |
| `effort.level` | Reasoning effort |
| `thinking.enabled` | Extended thinking on/off |
| `rate_limits.five_hour.used_percentage` | 5-hour rate limit % (Pro/Max) |
| `rate_limits.seven_day.used_percentage` | 7-day rate limit % (Pro/Max) |
| `vim.mode` | Vim mode if enabled |
| `agent.name` | Agent name when running with `--agent` |
| `output_style.name` | Active output style |

For the full schema, see Anthropic's [statusline docs](https://code.claude.com/docs/en/statusline).

## How it works

- **hooks.json** registers a `Stop` hook (writes last-response epoch) and a `SessionStart` hook (cost baseline reset on `/clear`, carry update on `/resume`, plus state pruning) — these activate automatically on install
- **setup skill** (`/statusline:setup`) copies `statusline.sh` and `cost-display.py` to `~/.claude/bin/` and patches `~/.claude/settings.json` to wire it up. Hook scripts run directly from the plugin root, so they update with the plugin automatically
- **update skill** (`/statusline:update`) re-syncs the deployed `statusline.sh` and `cost-display.py` with the plugin's latest, prompting before overwriting any customizations
- **refreshInterval: 30** makes the "ago" counter tick every 30 seconds without needing to hit Enter
- The "ago" clock is keyed by session ID (PPID fallback) so each Claude Code window has its own independent timer

### Hooks footprint and privacy

The plugin installs two hooks. Neither makes network calls or sends telemetry — every script only reads the JSON Claude Code already pipes in and writes small files under `~/.claude/`.

| Hook | When it fires | What it does |
|------|---------------|--------------|
| `Stop` | After every Claude response | Writes a unix epoch to `~/.claude/.session_stops/<session_id>` so the statusline can compute "X ago". Async, non-blocking. |
| `SessionStart` | When Claude Code starts (including after `/clear` and `/resume`) | If `source == 'clear'`, writes a cost baseline so `cost:$X.YZ` resets to `$0.00` for the new session. If `source == 'resume'`, writes a carry value so the displayed cost picks up where the prior session left off. Also prunes plugin state files older than 30 days. |

All scripts live under `${CLAUDE_PLUGIN_ROOT}/scripts/` and are plain Python/bash you can read in seconds.

## Reverting

The setup skill creates a timestamped backup of `~/.claude/settings.json` each run. To revert:

```bash
ls -t ~/.claude/settings.json.bak.* | head -1 | xargs -I{} cp {} ~/.claude/settings.json
```

Then restart Claude Code.

---

## Appendix: Salesforce org indicator

If you work in a Salesforce repo with the `sf` CLI configured, line 1 also shows the active target org so you know at a glance which org you're pointed at:

```
my-sfdc-project  [main]  ☁ my-prod-org
Opus 4.7  [xhigh]  ctx:12%  cost:$0.43  5/7 Thu 1:22 PM (2min ago)
```

- Auto-detected — appears only if `.sf/config.json` exists in the current dir or `~/.sf/config.json`. Invisible to everyone else.
- **Red when the org is production**, yellow when it's a sandbox or scratch org. Detection is based on the actual `isSandbox`/`isScratch` flags from `~/.sfdx/<username>.json` (not the alias name) — so an alias called `prod-mirror` pointing to a sandbox correctly shows yellow, and a sandbox alias accidentally named without `prod` still gets the right color. Falls back to the alias-name check only if the auth file isn't readable.

If you don't use `sf`, ignore this — the statusline behaves identically without it.
