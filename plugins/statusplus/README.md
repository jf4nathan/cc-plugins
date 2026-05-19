# statusplus

A compact Claude Code statusline that surfaces the things you actually want to know at a glance: where you are, what's changed in git, what model you're on, how much context and money you've burned, and how long since Claude last replied. Two lines by default; an optional third line carries a short LLM-generated headline of the current session.

> **Platform:** Unix-only (bash + python3). Works on macOS, Linux, WSL, or Git Bash on Windows. Native Windows PowerShell is not supported.

## Install

Add the marketplace once, then install the plugin:

```
/plugin marketplace add jf4nathan/cc-plugins
/plugin install statusplus@cc-plugins
/statusplus:statusplus-setup
```

Restart Claude Code. Done. The setup skill copies the scripts to `~/.claude/bin/`, writes the `statusLine` block into `~/.claude/settings.json` automatically (with a backup), and tells you to restart.

> **Already have a `statusLine` configured?** The setup skill detects an existing `statusLine` block and asks before replacing it. The previous config is always preserved in a timestamped `~/.claude/settings.json.bak.*` backup.

## What it looks like

In a regular repo (clean tree, nothing to flag):

```
my-project  [my-feature-branch]
Opus 4.7  [xhi]  ▓▓▒▒▒▒▒▒▒▒▒▒ 14%  $1.27  (3m)
```

With uncommitted edits, an untracked file, and one unpushed commit:

```
my-project  [my-feature-branch]  +12/-3/++45 (1)
Opus 4.7  [xhi]  ▓▓▒▒▒▒▒▒▒▒▒▒ 14%  $1.27  (3m)
```

In a worktree (`git worktree add ../wt-feature feature-branch`) — origin repo name surfaces so the worktree and cwd basename don't collapse:

```
my-project  ⌥wt-feature  [feature-branch]
Opus 4.7  [xhi]  ▓▓▒▒▒▒▒▒▒▒▒▒ 18%  $2.41  (1m)
```

On a large-context model (1M), the bar color reflects absolute token usage rather than just percentage — yellow above 200k tokens, red above 400k:

```
my-project  [my-feature-branch]
Sonnet 4.6 1M  ▓▓▓▒▒▒▒▒▒▒▒▒ 25%  $1.80  (5m)
```

When you're near the context limit (bar turns bold red ≥80%, or ≥400k tokens on large-context models):

```
my-project  [my-feature-branch]
Opus 4.7  [xhi]  ▓▓▓▓▓▓▓▓▓▓▒▒ 87%  $5.62  (12s)
```

With the optional LLM headline enabled (see below):

```
my-project  [my-feature-branch]  +12/-3/++45 (1)
Opus 4.7  [xhi]  ▓▓▒▒▒▒▒▒▒▒▒▒ 14%  $1.27  (3m)
Pinned Dependencies Receive Major Upgrades
```

## What's on the statusline

**Line 1 (location):**
- Current directory, bold — or the origin repo name when you're inside a linked worktree, so the worktree name isn't repeated
- `⌥worktree-name` if you're inside a `git worktree add` checkout (so you don't lose track of which worktree this terminal is in)
- `[branch]` in cyan when you're in a git repo, hidden in worktrees when it duplicates the worktree name
- Compact git status in dim gray: `+A/-R/++N (U)` where `+A/-R` is added/removed lines vs `HEAD`, `++N` is total lines in untracked files, and `(U)` is commits ahead of `@{upstream}`. Each segment renders only when non-zero — a clean tree with no unpushed commits adds nothing. Subprocess timeout is 3s; on a stalled filesystem the whole segment goes silent rather than hanging the statusline.

**Line 2 (session):**
- Model display name, blue — shortened automatically (`Claude Sonnet 4.6 (1M context)` → `Sonnet 4.6 1M`)
- `[effort]` blue, when the model supports a reasoning effort level — shortened to `lo/med/hi/xhi/max`
- Context progress bar (12-char shade fill `▓▒`) + percentage, color-coded by absolute token count:
  - purple — under 200k tokens (safe)
  - yellow — 200k–400k tokens (cost ramping)
  - bold red — over 400k tokens or over 80% of context window (whichever fires first)
- `$X.YZ` cyan, resets when you `/clear`, picks up where you left off after `/resume`
- Session age `(Nm)` since Claude last responded, color-coded:
  - bold red <5m (prompt cache still warm)
  - yellow <30m
  - green <2h
  - cyan <8h
  - dim gray after
  - switches to a date/time stamp once the session is older than 24h

## Optional: LLM headline on line 3

statusplus can also print a short LLM-generated "newspaper headline" of what the current Claude Code session is about, on a third line in italic yellow. **Off by default** — turn it on by running `/statusplus:statusplus-llm-setup`. The skill walks you through choosing a provider (Anthropic or any OpenAI-compatible endpoint), pasting an API key, and picking a model, then runs a one-shot test call.

```
my-project  [main]
Opus 4.7  [xhi]  ▓▓▒▒▒▒▒▒▒▒▒▒ 14%  $1.27  (3m)
Wiring LLM Summaries Into Statusplus
```

How it works:
- Statusline renders fast. The headline is read from a per-session cache file (typical lookup: <10ms).
- A **detached** background subprocess refreshes the cache (default TTL 60s) by sending a window of user/assistant messages to your chosen LLM. By default this is the **first 2 messages** (goal anchor) + **last 6 messages** (current state), merged and deduplicated — so the headline reflects both what the session started with and where it is now. Config-only slash commands (`/model`, `/effort`, `/clear`, etc.) are skipped so they don't pollute the anchor. The foreground statusline never blocks on the API.
- Misconfigured key, network blip, or empty transcript all collapse to "line 3 is empty" — never a broken statusline.

**Cost shape.** With the default 60s cache TTL and ~500 tokens of conversation context per call, you're looking at roughly $0.001/hr at gpt-4.1-mini, or ~$0.0001/hr at gpt-4.1-nano. Anthropic's Haiku 4.5 sits in between. Idle sessions don't refresh — the next call only fires when something else triggers the statusline (a keystroke, a new response, the 30s `refreshInterval`).

**Privacy note.** If you choose an OpenAI-compatible endpoint, transcript content will be sent there in addition to Anthropic. If you work with regulated data (PHI, PII, customer secrets), stick with Anthropic (same trust surface as Claude Code itself) or run a local Ollama endpoint. The setup skill warns explicitly before storing a non-Anthropic key — don't dismiss that prompt without a real answer.

To change the model, endpoint, key, or to disable the feature entirely, re-run `/statusplus:statusplus-llm-setup`. Config lives at `~/.claude/.statusplus/config.json` (`chmod 600`); cached summaries live at `~/.claude/.statusplus/cache/<session_id>.summary`.

## Customizing

Want a different layout, color scheme, or to add/remove fields? **The fastest way is to ask Claude.** Open a session and say something like:

- *"In `~/.claude/bin/statusline.sh`, change the branch color from cyan to magenta"*
- *"Add the API duration field (`cost.total_api_duration_ms`) to my statusline, formatted as seconds"*
- *"Hide the 'ago' timestamp on line 2"*
- *"Show vim mode when `vim.mode` is set"*
- *"Make the time format 24-hour instead of 12-hour"*

The script is plain bash + python and is already documented inline. Claude can read it, make the change, and you just restart Claude Code to see the result.

> **Picking up plugin updates.** The plugin's bundled scripts are *copied* into `~/.claude/bin/` at install time, so customizations there are yours and won't be overwritten. After `/plugin marketplace update cc-plugins` (or any plugin upgrade), run `/statusplus:statusplus-update` to sync the deployed copies with the plugin's latest. The skill detects local edits and asks before replacing them — so you can keep your customizations and update only the files you haven't touched.

### Available data fields

The statusline script receives the full Claude Code session JSON on stdin. The most useful fields:

| Field | Purpose |
|-------|---------|
| `model.display_name`, `model.id` | Model name |
| `workspace.current_dir`, `cwd` | Current dir |
| `workspace.git_worktree` | Worktree name (if in one) |
| `session_name` | Custom name from `/rename` |
| `context_window.used_percentage` | Context % used |
| `context_window.used_tokens` | Absolute token count (used for 200k/400k color thresholds) |
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
- **setup skill** (`/statusplus:statusplus-setup`) copies `statusline.sh`, `cost-display.py`, and `llm-summary.py` to `~/.claude/bin/` and patches `~/.claude/settings.json` to wire it up. Hook scripts run directly from the plugin root, so they update with the plugin automatically. `llm-summary.py` is dormant until you run `/statusplus:statusplus-llm-setup`.
- **update skill** (`/statusplus:statusplus-update`) re-syncs the deployed `statusline.sh`, `cost-display.py`, and `llm-summary.py` with the plugin's latest, prompting before overwriting any customizations; also patches `~/.claude/.statusplus/config.json` with any newly added default fields (without overwriting your existing values)
- **llm-setup skill** (`/statusplus:statusplus-llm-setup`) configures the optional line 3 headline — provider, endpoint, API key, model. Opt-in; safe to ignore if you don't want a third line.
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
Opus 4.7  [xhi]  ▓▓▒▒▒▒▒▒▒▒▒▒ 12%  $0.43  (2m)
```

- Auto-detected — appears only if `.sf/config.json` exists in the current dir or `~/.sf/config.json`. Invisible to everyone else.
- **Red when the org is production**, yellow when it's a sandbox or scratch org. Detection is based on the actual `isSandbox`/`isScratch` flags from `~/.sfdx/<username>.json` (not the alias name) — so an alias called `prod-mirror` pointing to a sandbox correctly shows yellow, and a sandbox alias accidentally named without `prod` still gets the right color. Falls back to the alias-name check only if the auth file isn't readable.

If you don't use `sf`, ignore this — the statusline behaves identically without it.
