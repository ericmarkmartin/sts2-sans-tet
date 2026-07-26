from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from headless.validate_episode import validate_episode


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value) + "\n", encoding="utf-8")


class ValidateEpisodeTests(unittest.TestCase):
    def make_episode(self) -> tuple[tempfile.TemporaryDirectory[str], Path]:
        temporary = tempfile.TemporaryDirectory()
        episode = Path(temporary.name) / "episode-0001"
        replay_dir = episode / "replays"
        replay_dir.mkdir(parents=True)
        replay = replay_dir / "combat-000.mcr"
        replay.write_bytes(b"replay")
        write_json(episode / "initial.state", {"state_type": "event"})
        (episode / "actions.jsonl").write_text(
            json.dumps(
                {"index": 0, "t": 1.0, "action": {"action": "proceed"}}
            )
            + "\n",
            encoding="utf-8",
        )
        (episode / "results.jsonl").write_text(
            json.dumps(
                {
                    "kind": "action_result",
                    "index": 0,
                    "t": 1.1,
                    "result": {"status": "ok"},
                    "state": {"state_type": "game_over"},
                }
            )
            + "\n",
            encoding="utf-8",
        )
        (episode / "game.log").write_text("test\n", encoding="utf-8")
        manifest = {
            "schema_version": 1,
            "episode_id": "episode-0001",
            "artifacts": {
                "initial_state": "initial.state",
                "actions": "actions.jsonl",
                "results": "results.jsonl",
                "game_log": "game.log",
                "combat_replays": [
                    {
                        "combat_index": 0,
                        "path": "replays/combat-000.mcr",
                        "size": replay.stat().st_size,
                        "sha256": hashlib.sha256(replay.read_bytes()).hexdigest(),
                    }
                ],
            },
            "grade": {
                "value": 0,
                "outcome": "loss",
                "terminal": True,
                "scale": {"loss": 0, "win": 1, "incomplete": None},
            },
            "summary": {
                "actions": 1,
                "final_state_type": "game_over",
                "outcome": "loss",
                "grade": 0,
            },
        }
        write_json(episode / "manifest.json", manifest)
        return temporary, episode

    def test_valid_episode(self) -> None:
        temporary, episode = self.make_episode()
        self.addCleanup(temporary.cleanup)
        report = validate_episode(episode)
        self.assertTrue(report.valid, report.errors)
        self.assertEqual(report.actions, 1)
        self.assertEqual(report.replays, 1)

    def test_detects_replay_corruption(self) -> None:
        temporary, episode = self.make_episode()
        self.addCleanup(temporary.cleanup)
        (episode / "replays/combat-000.mcr").write_bytes(b"changed")
        report = validate_episode(episode)
        self.assertFalse(report.valid)
        self.assertTrue(any("SHA-256 mismatch" in error for error in report.errors))

    def test_detects_action_result_gap(self) -> None:
        temporary, episode = self.make_episode()
        self.addCleanup(temporary.cleanup)
        (episode / "results.jsonl").write_text("", encoding="utf-8")
        report = validate_episode(episode)
        self.assertFalse(report.valid)
        self.assertIn(
            "each action must have exactly one action_result", report.errors
        )

    def test_rejects_artifact_path_escape(self) -> None:
        temporary, episode = self.make_episode()
        self.addCleanup(temporary.cleanup)
        manifest = json.loads((episode / "manifest.json").read_text())
        manifest["artifacts"]["initial_state"] = "../initial.state"
        write_json(episode / "manifest.json", manifest)
        report = validate_episode(episode)
        self.assertFalse(report.valid)
        self.assertTrue(any("escapes episode directory" in e for e in report.errors))

    def test_detects_inconsistent_grade(self) -> None:
        temporary, episode = self.make_episode()
        self.addCleanup(temporary.cleanup)
        manifest = json.loads((episode / "manifest.json").read_text())
        manifest["grade"]["value"] = 1
        write_json(episode / "manifest.json", manifest)
        report = validate_episode(episode)
        self.assertFalse(report.valid)
        self.assertTrue(any("does not match outcome" in e for e in report.errors))


if __name__ == "__main__":
    unittest.main()
