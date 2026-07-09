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

    def test_privacy_consent_describes_opening_transcript_window(self):
        setup = (
            PLUGIN / "skills" / "statusplus-llm-setup" / "SKILL.md"
        ).read_text(encoding="utf-8")
        self.assertIn("opening session transcript window", setup)
        self.assertIn("anchored at session start", setup)
        self.assertIn("12,000 characters", setup)
        self.assertNotIn("last few", setup.lower())


    # --- Final-fix findings (findings 1-4) ---

    def test_readme_no_resume_carry_claim(self):
        """Finding 1: README must not claim SessionStart writes a carry on /resume."""
        readme = (PLUGIN / "README.md").read_text(encoding="utf-8")
        self.assertNotIn("carry update on /resume", readme)
        self.assertNotIn("writes a carry value", readme)
        # Accurate description: /clear writes one-shot reset marker; /resume uses accumulator
        self.assertIn("one-shot reset marker", readme)
        self.assertIn("accumulator", readme)

    def test_setup_skill_no_user_prompt_submit(self):
        """Finding 2: setup SKILL.md must not reference nonexistent UserPromptSubmit hook."""
        setup = (
            PLUGIN / "skills" / "statusplus-setup" / "SKILL.md"
        ).read_text(encoding="utf-8")
        self.assertNotIn("UserPromptSubmit", setup)

    def test_update_skill_step1_prose_names_llm_summary(self):
        """Finding 3: update SKILL.md Step 1 lead-in prose must name llm-summary.py."""
        update = (
            PLUGIN / "skills" / "statusplus-update" / "SKILL.md"
        ).read_text(encoding="utf-8")
        step1_section = update.split("### 1. Check what would change")[1].split("### 2.")[0]
        step1_prose = step1_section.split("```")[0]
        self.assertIn("llm-summary.py", step1_prose)


if __name__ == "__main__":
    unittest.main()
