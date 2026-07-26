from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from benchmark_headless_episode import (
    allocate_episode_dir,
    choose_tactical_combat_action,
)


def combat_state(
    *,
    hand: list[dict],
    enemies: list[dict],
    block: int = 0,
) -> dict:
    return {
        "state_type": "monster",
        "battle": {"is_play_phase": True, "enemies": enemies},
        "player": {"block": block, "hand": hand},
    }


class EpisodeAllocationTests(unittest.TestCase):
    def test_allocates_first_unused_number(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "episode-0001").mkdir()
            allocated = allocate_episode_dir(root, None)
            self.assertEqual(allocated.name, "episode-0002")
            self.assertTrue(allocated.is_dir())

    def test_rejects_nonempty_explicit_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            explicit = Path(directory) / "chosen"
            explicit.mkdir()
            (explicit / "existing").write_text("preserve", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "not empty"):
                allocate_episode_dir(Path(directory), explicit)


class TacticalPolicyTests(unittest.TestCase):
    def test_kills_attacking_enemy_before_blocking(self) -> None:
        state = combat_state(
            hand=[
                {
                    "index": 0,
                    "id": "STRIKE_IRONCLAD",
                    "type": "Attack",
                    "description": "Deal 6 damage.",
                    "target_type": "AnyEnemy",
                    "can_play": True,
                },
                {
                    "index": 1,
                    "id": "DEFEND_IRONCLAD",
                    "type": "Skill",
                    "description": "Gain 5 Block.",
                    "target_type": "Self",
                    "can_play": True,
                },
            ],
            enemies=[
                {
                    "entity_id": "weak",
                    "hp": 6,
                    "block": 0,
                    "intents": [{"type": "Attack", "label": "9"}],
                },
                {
                    "entity_id": "idle",
                    "hp": 30,
                    "block": 0,
                    "intents": [],
                },
            ],
        )
        self.assertEqual(
            choose_tactical_combat_action(state),
            {"action": "play_card", "card_index": 0, "target": "weak"},
        )

    def test_blocks_nonlethal_incoming_damage(self) -> None:
        state = combat_state(
            hand=[
                {
                    "index": 0,
                    "id": "STRIKE_IRONCLAD",
                    "type": "Attack",
                    "description": "Deal 6 damage.",
                    "target_type": "AnyEnemy",
                    "can_play": True,
                },
                {
                    "index": 1,
                    "id": "DEFEND_IRONCLAD",
                    "type": "Skill",
                    "description": "Gain 5 Block.",
                    "target_type": "Self",
                    "can_play": True,
                },
            ],
            enemies=[
                {
                    "entity_id": "enemy",
                    "hp": 30,
                    "block": 0,
                    "intents": [{"type": "Attack", "label": "8"}],
                }
            ],
        )
        self.assertEqual(
            choose_tactical_combat_action(state),
            {"action": "play_card", "card_index": 1},
        )

    def test_returns_none_outside_play_phase(self) -> None:
        state = combat_state(hand=[], enemies=[])
        state["battle"]["is_play_phase"] = False
        self.assertIsNone(choose_tactical_combat_action(state))


if __name__ == "__main__":
    unittest.main()
