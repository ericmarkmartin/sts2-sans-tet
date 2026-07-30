from __future__ import annotations

import json
import random
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

import headless.sts2_cli_episode as episode_module
from headless.compare_episodes import compare_episodes
from headless.sts2_cli_episode import choose_sts2_cli_action, run_episode


class Sts2CliPolicyTests(unittest.TestCase):
    def test_targets_engine_enemy_index(self) -> None:
        state = {
            "decision": "combat_play",
            "energy": 1,
            "hand": [
                {
                    "index": 3,
                    "cost": 1,
                    "can_play": True,
                    "target_type": "AnyEnemy",
                }
            ],
            "enemies": [{"index": 7, "hp": 10}],
        }
        self.assertEqual(
            choose_sts2_cli_action(state, random.Random(0)),
            {
                "cmd": "action",
                "action": "play_card",
                "args": {"card_index": 3, "target_index": 7},
            },
        )

    def test_ends_turn_without_playable_card(self) -> None:
        state = {
            "decision": "combat_play",
            "energy": 0,
            "hand": [{"index": 0, "cost": 1, "can_play": True}],
            "enemies": [],
        }
        self.assertEqual(
            choose_sts2_cli_action(state, random.Random(0)),
            {"cmd": "action", "action": "end_turn"},
        )

    def test_prefers_heal_at_rest_site(self) -> None:
        state = {
            "decision": "rest_site",
            "options": [
                {"index": 0, "option_id": "SMITH", "is_enabled": True},
                {"index": 1, "option_id": "HEAL", "is_enabled": True},
            ],
        }
        self.assertEqual(
            choose_sts2_cli_action(state, random.Random(0)),
            {
                "cmd": "action",
                "action": "choose_option",
                "args": {"option_index": 1},
            },
        )

    def test_game_over_is_terminal(self) -> None:
        self.assertIsNone(
            choose_sts2_cli_action(
                {"decision": "game_over", "victory": False}, random.Random(0)
            )
        )


class Sts2CliEpisodeTests(unittest.TestCase):
    def test_records_and_validates_terminal_episode(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        dll = root / "Sts2Headless.dll"
        dll.write_bytes(b"simulator")
        states = [
            {
                "type": "decision",
                "decision": "event_choice",
                "observation_schema": "sts2-cli.observation.v1",
            },
            {
                "type": "decision",
                "decision": "game_over",
                "victory": False,
                "act": 1,
                "floor": 2,
                "player": {"hp": 0},
            },
        ]

        class FakeCli:
            ready = {"type": "ready", "version": "test"}

            def __init__(self, *args, **kwargs):
                self._states = iter(states)

            def send(self, command):
                return next(self._states)

            def close(self):
                pass

        args = Namespace(
            cli_dll=dll,
            cli_lib=None,
            game_data_dir=None,
            dotnet="dotnet",
            character="Ironclad",
            ascension=0,
            seed="test",
            policy_seed=0,
            lang="en",
            observation_mode="human",
            max_actions=5,
            episodes_dir=root / "episodes",
            episode_dir=None,
        )
        with patch.object(episode_module, "Sts2Cli", FakeCli):
            episode = run_episode(args)

        manifest = json.loads(
            (episode / "manifest.json").read_text(encoding="utf-8")
        )
        self.assertEqual(manifest["grade"]["value"], 0)
        self.assertEqual(manifest["summary"]["actions"], 1)

    def test_episode_comparison_ignores_timings(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        left = root / "left"
        right = root / "right"
        left.mkdir()
        right.mkdir()
        for episode, timing in ((left, 1.0), (right, 99.0)):
            (episode / "initial.state").write_text(
                '{"decision":"map_select"}\n', encoding="utf-8"
            )
            (episode / "actions.jsonl").write_text(
                json.dumps(
                    {
                        "index": 0,
                        "t": timing,
                        "action": {"cmd": "action", "action": "proceed"},
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            (episode / "results.jsonl").write_text(
                json.dumps(
                    {
                        "kind": "action_result",
                        "index": 0,
                        "t": timing,
                        "state": {"decision": "game_over", "victory": False},
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            (episode / "manifest.json").write_text(
                json.dumps(
                    {
                        "grade": {
                            "value": 0,
                            "outcome": "loss",
                            "terminal": True,
                        },
                        "summary": {
                            "actions": 1,
                            "final_state_type": "game_over",
                            "act": 1,
                            "floor": 2,
                            "final_hp": 0,
                        },
                    }
                )
                + "\n",
                encoding="utf-8",
            )
        result = compare_episodes(left, right)
        self.assertTrue(result["deterministic"], result)

        right_actions = json.loads(
            (right / "actions.jsonl").read_text(encoding="utf-8")
        )
        right_actions["action"]["action"] = "end_turn"
        (right / "actions.jsonl").write_text(
            json.dumps(right_actions) + "\n", encoding="utf-8"
        )
        result = compare_episodes(left, right)
        self.assertFalse(result["deterministic"], result)
        self.assertEqual(result["actions"]["first_mismatch"], 0)


if __name__ == "__main__":
    unittest.main()
