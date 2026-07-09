# Statusplus 1.7.1 Reconciliation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade this repository's Statusplus plugin to Spark's 1.7.1 runtime behavior while preserving local Windows, marketplace, author, and skill-name adaptations.

**Architecture:** Use Spark's tested runtime scripts as the upstream implementation, then layer only documented repository-specific adaptations onto metadata and process documentation. Add standard-library regression tests that run scripts in isolated temporary home directories, so cost state and headline caches never touch the developer's real `~/.claude`.

**Tech Stack:** Python 3 standard library (`unittest`, `subprocess`, `tempfile`, `importlib`, `unittest.mock`), JSON, Markdown, Bash statusline integration.

## Global Constraints

- Modify only `C:\Users\jonat\Desktop\Cursor Projects\cc-plugins`.
- Treat `C:\Users\jonat\Desktop\Cursor Projects\3-spark-advisors\spark-claude-plugins` as read-only.
- Target Statusplus version `1.7.1`.
- Preserve explicit Windows Bash discovery and tolerant `chmod` handling.
- Preserve `jf4nathan/cc-plugins`, `statusplus@cc-plugins`, local author email, and full local skill command names.
- Preserve unknown user configuration keys during migration.
- Do not add third-party test dependencies.
- Do not create a git commit unless the user explicitly requests one.

---

### Task 1: Cost accumulator and clear/resume behavior

**Files:**
- Create: `tests/statusplus_test_utils.py`
- Create: `tests/test_statusplus_cost.py`
- Modify: `plugins/statusplus/scripts/cost-display.py`
- Modify: `plugins/statusplus/scripts/clear-cost-baseline.py`

**Interfaces:**
- Consumes: JSON on stdin with `session_id`, `cost.total_cost_usd`, or SessionStart hook fields.
- Produces: two-decimal accumulated cost on stdout and atomic `~/.claude/.session_cost/<sid>.json` state.

- [ ] **Step 1: Add the isolated script runner**

Create `tests/statusplus_test_utils.py`:

```python
import json
import os
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "plugins" / "statusplus" / "scripts"


def run_script(script_name, payload, home, *args):
    env = os.environ.copy()
    env.update(
        {
            "HOME": str(home),
            "USERPROFILE": str(home),
            "PYTHONIOENCODING": "utf-8",
        }
    )
    return subprocess.run(
        [sys.executable, str(SCRIPTS / script_name), *args],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )
```

- [ ] **Step 2: Add failing cost and hook regression tests**

Create `tests/test_statusplus_cost.py`:

```python
import json
import math
import tempfile
import unittest
from pathlib import Path

from statusplus_test_utils import run_script


class CostDisplayTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.home = Path(self.tempdir.name)

    def tearDown(self):
        self.tempdir.cleanup()

    def render(self, live, sid="session"):
        return run_script(
            "cost-display.py",
            {"session_id": sid, "cost": {"total_cost_usd": live}},
            self.home,
        )

    def test_out_of_order_render_does_not_double_count(self):
        self.assertEqual(self.render(10).stdout, "10.00\n")
        self.assertEqual(self.render(9.5).stdout, "10.00\n")
        self.assertEqual(self.render(11).stdout, "11.00\n")

    def test_state_is_atomic_per_session_json(self):
        self.assertEqual(self.render(4).stdout, "4.00\n")
        state_path = self.home / ".claude" / ".session_cost" / "session.json"
        self.assertEqual(
            json.loads(state_path.read_text(encoding="utf-8")),
            {"prev_live": 4.0, "total": 4.0},
        )
        self.assertEqual(list(state_path.parent.glob(".tmp-*")), [])

    def test_legacy_state_migrates_once(self):
        root = self.home / ".claude"
        (root / ".session_cost").mkdir(parents=True)
        (root / ".session_cost_displayed").mkdir()
        (root / ".session_cost" / "legacy").write_text("7", encoding="utf-8")
        (root / ".session_cost_displayed" / "legacy").write_text("5", encoding="utf-8")
        self.assertEqual(self.render(8, "legacy").stdout, "6.00\n")
        state = json.loads(
            (root / ".session_cost" / "legacy.json").read_text(encoding="utf-8")
        )
        self.assertEqual(state, {"prev_live": 8.0, "total": 6.0})

    def test_clear_creates_and_consumes_reset_marker(self):
        hook = run_script(
            "clear-cost-baseline.py",
            {
                "hook_event_name": "SessionStart",
                "source": "clear",
                "session_id": "cleared",
            },
            self.home,
        )
        self.assertEqual(hook.returncode, 0)
        marker = self.home / ".claude" / ".session_cost_reset" / "cleared"
        self.assertTrue(marker.exists())
        self.assertEqual(self.render(25, "cleared").stdout, "0.00\n")
        self.assertFalse(marker.exists())
        state = json.loads(
            (
                self.home
                / ".claude"
                / ".session_cost"
                / "cleared.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(state, {"prev_live": 25.0, "total": 0.0})

    def test_resume_hook_does_not_create_cross_session_carry(self):
        result = run_script(
            "clear-cost-baseline.py",
            {
                "hook_event_name": "SessionStart",
                "source": "resume",
                "session_id": "resumed",
            },
            self.home,
        )
        self.assertEqual(result.returncode, 0)
        carry = self.home / ".claude" / ".session_cost_carry"
        self.assertFalse(carry.exists())

    def test_invalid_or_negative_live_is_silent(self):
        payloads = [
            {"session_id": "s", "cost": {"total_cost_usd": -1}},
            {"session_id": "s", "cost": {"total_cost_usd": math.nan}},
            {"session_id": "s", "cost": {"total_cost_usd": "not-a-number"}},
            {"session_id": "s", "cost": {}},
        ]
        for payload in payloads:
            with self.subTest(payload=payload):
                result = run_script("cost-display.py", payload, self.home)
                self.assertEqual(result.returncode, 0)
                self.assertEqual(result.stdout, "")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run the cost tests and verify the current implementation fails**

Run:

```powershell
$env:PYTHONIOENCODING = "utf-8"
python -B -m unittest discover -s tests -p "test_statusplus_cost.py" -v
```

Expected: failures for out-of-order accounting, JSON state, legacy migration,
clear markers, resume isolation, and invalid input. Failures must be assertions,
not test import or fixture errors.

- [ ] **Step 4: Adopt Spark's 1.7.1 cost scripts**

Copy these files from the read-only Spark tree into this repository:

```powershell
Copy-Item -LiteralPath `
  "C:\Users\jonat\Desktop\Cursor Projects\3-spark-advisors\spark-claude-plugins\plugins\statusplus\scripts\cost-display.py" `
  -Destination "plugins\statusplus\scripts\cost-display.py"
Copy-Item -LiteralPath `
  "C:\Users\jonat\Desktop\Cursor Projects\3-spark-advisors\spark-claude-plugins\plugins\statusplus\scripts\clear-cost-baseline.py" `
  -Destination "plugins\statusplus\scripts\clear-cost-baseline.py"
```

Do not alter the accumulator algorithm. It must retain sanitized session IDs,
atomic `os.replace`, stale-render high-water handling, reset-marker consumption,
legacy migration, and raw-live fallback on unexpected filesystem errors.

- [ ] **Step 5: Run the cost tests and verify they pass**

Run the Step 3 command.

Expected: six tests pass with no warnings or tracebacks.

---

### Task 2: Stable opening-session LLM headline

**Files:**
- Create: `tests/test_statusplus_llm_summary.py`
- Modify: `plugins/statusplus/scripts/llm-summary.py`

**Interfaces:**
- Consumes: transcript JSONL and Statusplus provider configuration.
- Produces: a normalized maximum-14-word summary plus `<sid>.summary` and optional `<sid>.full` cache files.

- [ ] **Step 1: Add failing transcript and normalization tests**

Create `tests/test_statusplus_llm_summary.py`:

```python
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from statusplus_test_utils import SCRIPTS


def load_module():
    path = SCRIPTS / "llm-summary.py"
    spec = importlib.util.spec_from_file_location("statusplus_llm_summary", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_jsonl(path, records):
    path.write_text(
        "".join(json.dumps(record) + "\n" for record in records),
        encoding="utf-8",
    )


def message(role, text, **extra):
    payload = {"role": role, "content": text}
    payload.update(extra)
    return {"type": role, "message": payload}


class LlmSummaryTests(unittest.TestCase):
    def setUp(self):
        self.module = load_module()
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)

    def tearDown(self):
        self.tempdir.cleanup()

    def test_start_window_excludes_late_messages(self):
        transcript = self.root / "session.jsonl"
        records = [message("user", f"opening-{index}-" + "x" * 790) for index in range(20)]
        records.append(message("user", "UNIQUE_LATE_MARKER"))
        write_jsonl(transcript, records)
        text, budget_full = self.module.build_transcript(str(transcript))
        self.assertTrue(budget_full)
        self.assertNotIn("UNIQUE_LATE_MARKER", text)

    def test_transcript_filters_noise_and_caps_messages(self):
        transcript = self.root / "session.jsonl"
        records = [
            message("user", "hidden meta", isMeta=True),
            message("user", "<local-command-caveat>hidden"),
            {
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "content": [
                        {"type": "thinking", "thinking": "hidden"},
                        {"type": "tool_use", "name": "hidden"},
                        {"type": "text", "text": "A" * 1000},
                    ],
                },
            },
        ]
        write_jsonl(transcript, records)
        text, budget_full = self.module.build_transcript(str(transcript))
        self.assertFalse(budget_full)
        self.assertNotIn("hidden meta", text)
        self.assertNotIn("local-command", text)
        self.assertNotIn("thinking", text)
        self.assertEqual(text.count("A"), 800)

    def test_fallback_transcript_never_freezes(self):
        fallback = self.root / "newest.jsonl"
        write_jsonl(
            fallback,
            [message("user", f"opening-{index}-" + "x" * 790) for index in range(20)],
        )
        text, budget_full = self.module.build_transcript(
            str(self.root / "missing.jsonl")
        )
        self.assertTrue(text)
        self.assertFalse(budget_full)

    def test_last_ai_title_is_added_to_prompt(self):
        transcript = self.root / "session.jsonl"
        write_jsonl(
            transcript,
            [
                {"type": "ai-title", "title": "Old title"},
                {"type": "ai-title", "title": "Final title"},
            ],
        )
        title = self.module.find_title(str(transcript))
        prompt = self.module.build_user_prompt("User: reconcile plugin", title)
        self.assertEqual(title, "Final title")
        self.assertIn("Final title", prompt)
        self.assertNotIn("Old title", prompt)

    def test_postprocess_is_ascii_and_capped_at_fourteen_words(self):
        raw = "“one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen”—."
        result = self.module.postprocess(raw)
        self.assertTrue(result.isascii())
        self.assertEqual(len(result.split()), 14)

    def test_frozen_foreground_never_spawns_refresh(self):
        with mock.patch.object(self.module, "CACHE_DIR", self.root):
            (self.root / "s.summary").write_text("Stable headline", encoding="utf-8")
            (self.root / "s.full").write_text("1", encoding="utf-8")
            with mock.patch.object(self.module, "spawn_refresh") as spawn:
                with mock.patch("sys.stdin.read", return_value=json.dumps({"session_id": "s"})):
                    with mock.patch("builtins.print") as output:
                        self.module.main()
        output.assert_called_once_with("Stable headline")
        spawn.assert_not_called()


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the headline tests and verify the current implementation fails**

Run:

```powershell
$env:PYTHONIOENCODING = "utf-8"
python -B -m unittest discover -s tests -p "test_statusplus_llm_summary.py" -v
```

Expected: failures because the current script lacks the opening-window tuple,
fallback freeze protection, AI-title prompt integration, 14-word normalization,
and `.full` behavior.

- [ ] **Step 3: Adopt Spark's 1.7.1 headline implementation**

Copy the runtime script:

```powershell
Copy-Item -LiteralPath `
  "C:\Users\jonat\Desktop\Cursor Projects\3-spark-advisors\spark-claude-plugins\plugins\statusplus\scripts\llm-summary.py" `
  -Destination "plugins\statusplus\scripts\llm-summary.py"
```

Retain the implementation unchanged except for replacing any abbreviated Spark
skill command in its top-level setup guidance with
`/statusplus:statusplus-llm-setup`.

- [ ] **Step 4: Run the headline tests and verify they pass**

Run the Step 2 command.

Expected: six tests pass with no real provider call.

---

### Task 3: Local adaptations, configuration migration, and documentation

**Files:**
- Create: `tests/test_statusplus_local_adaptations.py`
- Modify: `plugins/statusplus/.claude-plugin/plugin.json`
- Modify: `.claude-plugin/marketplace.json`
- Modify: `plugins/statusplus/README.md`
- Modify: `plugins/statusplus/skills/statusplus-setup/SKILL.md`
- Modify: `plugins/statusplus/skills/statusplus-update/SKILL.md`
- Modify: `plugins/statusplus/skills/statusplus-llm-setup/SKILL.md`

**Interfaces:**
- Consumes: existing Statusplus config JSON and repository installation context.
- Produces: consistent 1.7.1 metadata and skills that migrate old headline keys without losing unrelated configuration.

- [ ] **Step 1: Add failing metadata and local-adaptation tests**

Create `tests/test_statusplus_local_adaptations.py`:

```python
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins" / "statusplus"


class LocalAdaptationTests(unittest.TestCase):
    def test_versions_are_1_7_1(self):
        plugin = json.loads(
            (PLUGIN / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8")
        )
        marketplace = json.loads(
            (ROOT / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8")
        )
        entry = next(item for item in marketplace["plugins"] if item["name"] == "statusplus")
        self.assertEqual(plugin["version"], "1.7.1")
        self.assertEqual(entry["version"], "1.7.1")

    def test_local_identity_is_preserved(self):
        plugin_text = (
            PLUGIN / ".claude-plugin" / "plugin.json"
        ).read_text(encoding="utf-8")
        readme = (PLUGIN / "README.md").read_text(encoding="utf-8")
        self.assertIn("jonathan.y.tang@gmail.com", plugin_text)
        self.assertIn("jf4nathan/cc-plugins", readme)
        self.assertIn("statusplus@cc-plugins", readme)
        self.assertNotIn("spark-claude-plugins", readme)

    def test_full_local_skill_names_are_preserved(self):
        for relative, command in [
            ("statusplus-setup/SKILL.md", "/statusplus:statusplus-setup"),
            ("statusplus-update/SKILL.md", "/statusplus:statusplus-update"),
            ("statusplus-llm-setup/SKILL.md", "/statusplus:statusplus-llm-setup"),
        ]:
            text = (PLUGIN / "skills" / relative).read_text(encoding="utf-8")
            self.assertIn(command, text)

    def test_windows_bash_discovery_and_tolerant_chmod_remain(self):
        text = (
            PLUGIN / "skills" / "statusplus-setup" / "SKILL.md"
        ).read_text(encoding="utf-8")
        self.assertIn("Get-Command bash", text)
        self.assertIn("2>/dev/null || true", text)

    def test_new_headline_configuration_is_documented(self):
        update = (
            PLUGIN / "skills" / "statusplus-update" / "SKILL.md"
        ).read_text(encoding="utf-8")
        setup = (
            PLUGIN / "skills" / "statusplus-llm-setup" / "SKILL.md"
        ).read_text(encoding="utf-8")
        readme = (PLUGIN / "README.md").read_text(encoding="utf-8")
        for text in (update, setup):
            self.assertIn('"max_tokens": 50', text)
            self.assertNotIn('"head_messages"', text)
            self.assertNotIn('"tail_messages"', text)
        self.assertIn("12,000", readme)
        self.assertIn(".full", setup)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run adaptation tests and verify the version/config tests fail**

Run:

```powershell
$env:PYTHONIOENCODING = "utf-8"
python -B -m unittest discover -s tests -p "test_statusplus_local_adaptations.py" -v
```

Expected: local identity and Windows tests pass; version and new headline
configuration tests fail.

- [ ] **Step 3: Update metadata**

In `plugins/statusplus/.claude-plugin/plugin.json`, change only:

```json
"version": "1.7.1"
```

Retain the author email and all existing paths and keywords.

In `.claude-plugin/marketplace.json`, change the Statusplus entry's version to:

```json
"version": "1.7.1"
```

Do not alter any other plugin entry.

- [ ] **Step 4: Reconcile the setup skill**

Start from the current `statusplus-setup/SKILL.md`, preserving its Windows Bash
discovery, tolerant `chmod`, and full local command names. Replace the old cost
description with these rules:

- Cost is lifetime accumulated cost for the current session.
- State lives in one atomic JSON accumulator per session.
- `/clear` creates a one-shot reset marker consumed by the next render.
- `/resume` needs no cross-session transcript lookup or carry file.

Do not copy Spark's unconditional literal `bash` statusLine command.

- [ ] **Step 5: Reconcile the update skill**

Start from the current `statusplus-update/SKILL.md`. Keep the `cc-plugins`
marketplace command and full skill names. Update its deployed-file check to name
`statusline.sh`, `cost-display.py`, and `llm-summary.py`.

Replace the config migration block with logic that:

```python
defaults = {
    "max_tokens": 50,
    "timeout_s": 8,
    "cache_ttl_s": 60,
}
for key, value in defaults.items():
    config.setdefault(key, value)
if config.get("max_tokens") == 30:
    config["max_tokens"] = 50
config.pop("head_messages", None)
config.pop("tail_messages", None)
```

The surrounding write must serialize the original `config` mapping after these
changes, preserving unknown keys.

- [ ] **Step 6: Reconcile the LLM setup skill**

Start from the current `statusplus-llm-setup/SKILL.md`. Keep the existing
provider, privacy, endpoint, and credential workflow plus all full local skill
names. Make these exact configuration changes:

```json
{
  "max_tokens": 50,
  "timeout_s": 8,
  "cache_ttl_s": 60
}
```

Remove `head_messages` and `tail_messages`. Document:

- Opening transcript window capped at 12,000 prefixed characters.
- Individual message text capped at 800 characters.
- Final headline capped at 14 words.
- `<sid>.summary` contains the headline.
- `<sid>.full` prevents refresh after a successful full opening window.
- Fallback transcripts may populate cache but may not create `<sid>.full`.

Do not describe an empty-transcript invocation as an authentication test,
because the script returns before contacting the provider.

- [ ] **Step 7: Reconcile README behavior descriptions**

Keep all `cc-plugins` installation and update commands. Update the headline
section to describe the stable opening-session anchor, 12,000-character window,
14-word cap, and frozen `.full` cache. Remove claims about first-two/last-four
or rolling head/tail sampling.

Update the cost section to describe atomic per-session delta accumulation,
out-of-order render handling, `/clear` reset markers, and resume continuity.

- [ ] **Step 8: Run adaptation tests and verify they pass**

Run the Step 2 command.

Expected: five tests pass.

---

### Task 4: Full verification and source isolation

**Files:**
- Verify: all files under `plugins/statusplus`
- Verify: `.claude-plugin/marketplace.json`
- Verify: `tests/test_statusplus_*.py`
- Verify unchanged source: `C:\Users\jonat\Desktop\Cursor Projects\3-spark-advisors\spark-claude-plugins`

**Interfaces:**
- Consumes: completed working-tree reconciliation.
- Produces: evidence that tests, syntax, metadata, intentional diffs, and source isolation are correct.

- [ ] **Step 1: Run the complete regression suite**

```powershell
$env:PYTHONIOENCODING = "utf-8"
python -B -m unittest discover -s tests -p "test_statusplus_*.py" -v
```

Expected: 17 tests pass with no failures, errors, warnings, or provider calls.

- [ ] **Step 2: Compile every Statusplus Python script**

```powershell
$env:PYTHONIOENCODING = "utf-8"
python -m py_compile `
  "plugins\statusplus\scripts\cost-display.py" `
  "plugins\statusplus\scripts\clear-cost-baseline.py" `
  "plugins\statusplus\scripts\llm-summary.py" `
  "plugins\statusplus\scripts\write-stop-epoch.py"
```

Expected: exit code 0 and no output.

- [ ] **Step 3: Validate JSON metadata**

```powershell
$env:PYTHONIOENCODING = "utf-8"
python -c "import json,pathlib; files=['plugins/statusplus/.claude-plugin/plugin.json','plugins/statusplus/hooks/hooks.json','.claude-plugin/marketplace.json']; [json.loads(pathlib.Path(f).read_text(encoding='utf-8')) for f in files]; print('JSON valid')"
```

Expected: `JSON valid`.

- [ ] **Step 4: Review the final Spark comparison**

Run a no-index diff between the two `plugins/statusplus` directories. Confirm:

- `cost-display.py` and `clear-cost-baseline.py` match Spark.
- `llm-summary.py` differs only for the full local setup command, if Spark used
  an abbreviated command.
- `statusline.sh`, `hooks.json`, and `write-stop-epoch.py` have no substantive
  differences.
- Metadata, README, and skill differences correspond only to the approved local
  adaptations and corrected stale documentation.

- [ ] **Step 5: Confirm Spark remained untouched**

```powershell
git -C `
  "C:\Users\jonat\Desktop\Cursor Projects\3-spark-advisors\spark-claude-plugins" `
  status --short -- "plugins/statusplus"
```

Expected: no output.

- [ ] **Step 6: Review this repository's working tree**

Confirm the changed files are limited to the design and plan documents,
Statusplus runtime, Statusplus metadata/documentation/skills, marketplace
version, and focused tests. Leave unrelated pre-existing untracked log files
untouched.
