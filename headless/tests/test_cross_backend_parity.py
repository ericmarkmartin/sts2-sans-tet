from __future__ import annotations

import unittest

from headless.cross_backend_parity import (
    automatic_reconciliation_action,
    parity_diff,
    translate_standalone_action,
)


class CrossBackendParityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.standalone_event = {
            "decision": "event_choice",
            "context": {"act": 1, "floor": 1},
            "event_name": "Neow",
            "options": [
                {"index": 0, "title": "Fishing Rod", "is_locked": False}
            ],
            "player": {
                "hp": 80,
                "max_hp": 80,
                "gold": 99,
                "relics": [{"name": "Burning Blood"}],
                "potions": [],
            },
        }
        self.godot_event = {
            "state_type": "event",
            "run": {"act": 1, "floor": 1},
            "event": {
                "event_name": "Neow",
                "options": [
                    {
                        "index": 4,
                        "title": "Fishing Rod",
                        "is_locked": False,
                        "is_proceed": False,
                    }
                ],
            },
            "player": {
                "hp": 80,
                "max_hp": 80,
                "gold": 99,
                "relics": [{"name": "Burning Blood"}],
                "potions": [],
            },
        }

    def test_matching_event_checkpoint(self) -> None:
        self.assertEqual(parity_diff(self.standalone_event, self.godot_event), {})

    def test_upgraded_pile_card_names_are_canonicalized(self) -> None:
        standalone = {
            "decision": "combat_play",
            "context": {"act": 1, "floor": 2},
            "round": 1,
            "energy": 3,
            "hand": [],
            "enemies": [],
            "draw_pile": [{"name": "Defend", "upgraded": True}],
            "discard_pile": [],
            "exhaust_pile": [],
            "player": {},
        }
        godot = {
            "state_type": "monster",
            "run": {"act": 1, "floor": 2},
            "battle": {"round": 1, "enemies": []},
            "player": {
                "energy": 3,
                "hand": [],
                "draw_pile": [{"name": "Defend+"}],
                "discard_pile": [],
                "exhaust_pile": [],
            },
        }
        self.assertEqual(parity_diff(standalone, godot), {})

    def test_translates_event_by_title_not_index(self) -> None:
        translated = translate_standalone_action(
            self.standalone_event,
            {
                "cmd": "action",
                "action": "choose_option",
                "args": {"option_index": 0},
            },
            self.godot_event,
        )
        self.assertEqual(
            translated, {"action": "choose_event_option", "index": 4}
        )

    def test_translates_map_coordinate_to_option_index(self) -> None:
        standalone = {
            "decision": "map_select",
            "context": {"act": 1, "floor": 1},
            "choices": [{"col": 3, "row": 1, "type": "Monster"}],
            "player": {},
        }
        godot = {
            "state_type": "map",
            "run": {"act": 1, "floor": 1},
            "map": {
                "next_options": [
                    {"index": 9, "col": 3, "row": 1, "type": "Monster"}
                ]
            },
            "player": {},
        }
        translated = translate_standalone_action(
            standalone,
            {
                "action": "select_map_node",
                "args": {"col": 3, "row": 1},
            },
            godot,
        )
        self.assertEqual(
            translated, {"action": "choose_map_node", "index": 9}
        )

    def test_translates_target_to_entity_id(self) -> None:
        standalone = {
            "decision": "combat_play",
            "context": {"act": 1, "floor": 2},
            "energy": 1,
            "hand": [{"index": 0, "name": "Strike", "type": "Attack"}],
            "enemies": [{"index": 0, "name": "Shrinker Beetle"}],
            "player": {},
        }
        godot = {
            "state_type": "monster",
            "run": {"act": 1, "floor": 2},
            "battle": {
                "enemies": [
                    {
                        "entity_id": "SHRINKER_BEETLE_0",
                        "name": "Shrinker Beetle",
                    }
                ]
            },
            "player": {
                "hand": [{"index": 3, "name": "Strike", "type": "Attack"}]
            },
        }
        translated = translate_standalone_action(
            standalone,
            {
                "action": "play_card",
                "args": {"card_index": 0, "target_index": 0},
            },
            godot,
        )
        self.assertEqual(
            translated,
            {
                "action": "play_card",
                "card_index": 3,
                "target": "SHRINKER_BEETLE_0",
            },
        )

    def test_translates_upgraded_card_with_godot_plus_suffix(self) -> None:
        standalone = {
            "decision": "combat_play",
            "hand": [
                {
                    "index": 0,
                    "name": "Defend",
                    "type": "Skill",
                    "upgraded": True,
                }
            ],
            "enemies": [],
        }
        godot = {
            "state_type": "monster",
            "battle": {"is_play_phase": True, "enemies": []},
            "player": {
                "hand": [
                    {
                        "index": 4,
                        "name": "Defend+",
                        "type": "Skill",
                        "is_upgraded": True,
                    }
                ]
            },
        }
        translated = translate_standalone_action(
            standalone,
            {"action": "play_card", "args": {"card_index": 0}},
            godot,
        )
        self.assertEqual(
            translated,
            {"action": "play_card", "card_index": 4},
        )

    def test_auto_advances_only_proceed_event(self) -> None:
        godot = {
            **self.godot_event,
            "event": {
                "event_name": "Neow",
                "options": [
                    {
                        "index": 7,
                        "title": "Proceed",
                        "is_locked": False,
                        "is_proceed": True,
                    }
                ],
            },
        }
        expected = {
            "decision": "map_select",
            "context": {"act": 1, "floor": 1},
            "player": {},
        }
        self.assertEqual(
            automatic_reconciliation_action(expected, godot),
            {"action": "choose_event_option", "index": 7},
        )

    def test_claims_card_reward_before_proceeding(self) -> None:
        expected = {
            "decision": "card_reward",
            "cards": [{"name": "Headbutt", "type": "Attack"}],
            "player": {},
        }
        godot = {
            "state_type": "rewards",
            "rewards": {
                "items": [
                    {
                        "index": 3,
                        "type": "card",
                        "description": "Add a card to your deck.",
                    }
                ],
                "can_proceed": True,
            },
            "player": {},
        }
        self.assertEqual(
            automatic_reconciliation_action(expected, godot),
            {"action": "claim_reward", "index": 3},
        )


if __name__ == "__main__":
    unittest.main()
