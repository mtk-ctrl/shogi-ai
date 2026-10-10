#!/usr/bin/env python3
"""Regression tests for GitHub Issue and existing file-based match dispatch."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from dispatch_match_request import read_request, validate, dispatch_command


def valid_request():
    return {
        "request_id": "test",
        "ref_a": "main",
        "ref_b": "BASELINE_FILE",
        "games": "200",
        "shards": "20",
        "go_command": "go movetime 200",
        "max_plies": "300",
        "seed": "2026101020",
        "options_a": json.dumps({"AdaptiveLongThink": True, "PositionKnowledge": True,
                                 "PositionKnowledgeFile": "build/position-knowledge-v1.tsv"}),
        "options_b": json.dumps({"AdaptiveLongThink": True, "PositionKnowledge": True}),
    }


class MatchRequestDispatchTest(unittest.TestCase):
    def test_valid_owner_issue(self):
        req = valid_request()
        event = {"issue": {"title": "[KUMOJI MATCH] test",
                           "user": {"login": "mtk-ctrl"},
                           "body": json.dumps({**req, "dry_run": True})}}
        loaded, dry_run = read_request("issues", event, "mtk-ctrl", Path("unused"))
        self.assertTrue(dry_run)
        validated = validate(loaded, issue_request=True)
        self.assertEqual(validated["games"], 200)
        self.assertEqual(validated["shards"], 20)

    def test_other_author_rejected(self):
        event = {"issue": {"title": "[KUMOJI MATCH] test",
                           "user": {"login": "stranger"}, "body": json.dumps(valid_request())}}
        with self.assertRaisesRegex(ValueError, "author"):
            read_request("issues", event, "mtk-ctrl", Path("unused"))

    def test_unrelated_issue_rejected(self):
        event = {"issue": {"title": "ordinary issue", "user": {"login": "mtk-ctrl"},
                           "body": json.dumps(valid_request())}}
        with self.assertRaisesRegex(ValueError, "title"):
            read_request("issues", event, "mtk-ctrl", Path("unused"))

    def test_unsafe_ref_rejected(self):
        req = valid_request()
        req["ref_a"] = "../something"
        with self.assertRaisesRegex(ValueError, "unsafe engine ref"):
            validate(req, issue_request=True)

    def test_unsafe_command_rejected(self):
        req = valid_request()
        req["go_command"] = "go movetime 200\nquit"
        with self.assertRaisesRegex(ValueError, "bounded"):
            validate(req, issue_request=True)

    def test_unknown_issue_option_rejected(self):
        req = valid_request()
        req["options_a"] = json.dumps({"Danger": "value"})
        with self.assertRaisesRegex(ValueError, "unsupported"):
            validate(req, issue_request=True)

    def test_oversized_seed_rejected(self):
        req = valid_request()
        req["seed"] = "2147483647"
        with self.assertRaisesRegex(ValueError, "seed"):
            validate(req, issue_request=True)

    def test_unknown_field_rejected(self):
        req = valid_request()
        req["extra"] = "bad"
        with self.assertRaisesRegex(ValueError, "unexpected"):
            validate(req, issue_request=True)

    def test_existing_request_file_supported(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "request.json"
            path.write_text(json.dumps(valid_request()), encoding="utf-8")
            loaded, dry_run = read_request("push", {}, "mtk-ctrl", path)
            self.assertFalse(dry_run)
            self.assertEqual(validate(loaded, issue_request=False)["games"], 200)

    def test_no_shell_execution(self):
        command = dispatch_command(validate(valid_request(), issue_request=True), "mtk-ctrl/shogi-ai")
        self.assertEqual(command[:7], ["gh", "workflow", "run", "engine-match.yml",
                                       "--repo", "mtk-ctrl/shogi-ai", "--ref"])
        self.assertNotIn("sh", command[:3])


if __name__ == "__main__":
    unittest.main()
