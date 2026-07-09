import importlib.util
import json
import sys
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
        self.assertEqual(text.count("A"), 802)

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
            with mock.patch.object(
                self.module, "load_config", return_value={"api_key": "test-key"}
            ):
                with mock.patch.object(self.module, "spawn_refresh") as spawn:
                    stdin_payload = json.dumps({"session_id": "s"})
                    with mock.patch(
                        "sys.stdin", mock.Mock(read=mock.Mock(return_value=stdin_payload))
                    ):
                        with mock.patch.object(
                            sys.stdout.buffer, "write", wraps=sys.stdout.buffer.write
                        ) as write:
                            self.module.main()
        write.assert_called_once_with(b"Stable headline\n")
        spawn.assert_not_called()


if __name__ == "__main__":
    unittest.main()
