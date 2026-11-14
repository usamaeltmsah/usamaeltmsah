import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / ".github" / "scripts"))

from update_activity import END, START, build_lines, replace_section  # noqa: E402


def push(at: str, repo: str = "me/app", ref: str = "refs/heads/main") -> dict:
    return {"type": "PushEvent", "created_at": at, "repo": {"name": repo}, "payload": {"ref": ref}}


class BuildLinesTests(unittest.TestCase):
    def test_collapses_consecutive_pushes_to_same_branch(self):
        lines = build_lines([push("2026-01-01T10:00:00Z"), push("2026-01-01T11:00:00Z")])
        self.assertEqual(lines, ["⬆️ Pushed 2 times to `main` in [me/app](https://github.com/me/app)"])

    def test_orders_newest_first_and_respects_limit(self):
        events = [push(f"2026-01-0{d}T00:00:00Z", repo=f"me/r{d}") for d in range(1, 8)]
        lines = build_lines(events, limit=3)
        self.assertEqual(len(lines), 3)
        self.assertIn("me/r7", lines[0])

    def test_merged_pull_request(self):
        event = {
            "type": "PullRequestEvent",
            "created_at": "2026-01-01T00:00:00Z",
            "repo": {"name": "me/app"},
            "payload": {"action": "closed", "pull_request": {"number": 4, "merged": True}},
        }
        self.assertTrue(build_lines([event])[0].startswith("🔀 Merged PR [#4]"))

    def test_skips_unsupported_events(self):
        event = {"type": "ForkEvent", "created_at": "2026-01-01T00:00:00Z", "repo": {"name": "x/y"}, "payload": {}}
        self.assertEqual(build_lines([event]), [])


class ReplaceSectionTests(unittest.TestCase):
    def test_replaces_only_marked_section(self):
        readme = f"top\n{START}\nold\n{END}\nbottom"
        self.assertEqual(replace_section(readme, ["a", "b"]), f"top\n{START}\n1. a\n2. b\n{END}\nbottom")

    def test_missing_markers_raises(self):
        with self.assertRaises(ValueError):
            replace_section("no markers", ["a"])


if __name__ == "__main__":
    unittest.main()
