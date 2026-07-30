"""Semantic action translation and observation parity for STS2 backends."""

from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
from typing import Any


class ParityMappingError(RuntimeError):
    pass


def load_standalone_trace(
    episode_dir: Path,
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    episode_dir = episode_dir.resolve()
    initial = json.loads(
        (episode_dir / "initial.state").read_text(encoding="utf-8")
    )
    with (episode_dir / "actions.jsonl").open(encoding="utf-8") as file:
        action_records = [json.loads(line) for line in file if line.strip()]
    with (episode_dir / "results.jsonl").open(encoding="utf-8") as file:
        result_records = [json.loads(line) for line in file if line.strip()]
    results = {
        record["index"]: record["state"]
        for record in result_records
        if record.get("kind") == "action_result"
    }
    steps: list[dict[str, Any]] = []
    before = initial
    for expected_index, action_record in enumerate(action_records):
        index = action_record.get("index")
        if index != expected_index or index not in results:
            raise ParityMappingError(
                f"standalone trace has invalid action/result linkage at {expected_index}"
            )
        after = results[index]
        steps.append(
            {
                "source_index": index,
                "before": before,
                "action": action_record["action"],
                "after": after,
            }
        )
        before = after
    manifest = json.loads(
        (episode_dir / "manifest.json").read_text(encoding="utf-8")
    )
    return initial, steps, manifest


def standalone_phase(state: dict[str, Any]) -> str:
    return {
        "event_choice": "event",
        "map_select": "map",
        "combat_play": "combat",
        "card_reward": "card_reward",
        "card_select": "card_select",
        "bundle_select": "bundle_select",
        "rest_site": "rest_site",
        "shop": "shop",
        "game_over": "game_over",
    }.get(str(state.get("decision")), str(state.get("decision") or "unknown"))


def godot_phase(state: dict[str, Any]) -> str:
    state_type = str(state.get("state_type") or "unknown")
    if state_type in {"monster", "elite", "boss"}:
        return "combat"
    if state_type == "merchant":
        return "shop"
    return state_type


def _number(value: Any) -> int | float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return value
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _card(card: dict[str, Any]) -> dict[str, Any]:
    name = card.get("name")
    upgraded = bool(card.get("upgraded", card.get("is_upgraded", False)))
    if isinstance(name, str) and name.endswith("+"):
        name = name[:-1]
        upgraded = True
    return {
        "name": name,
        "type": card.get("type"),
        "cost": _number(card.get("cost")),
        "upgraded": upgraded,
    }


def _pile(cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized = [
        {
            "name": card["name"][:-1]
            if isinstance(card.get("name"), str) and card["name"].endswith("+")
            else card.get("name"),
            "upgraded": bool(
                card.get("upgraded", card.get("is_upgraded", False))
            )
            or (
                isinstance(card.get("name"), str)
                and card["name"].endswith("+")
            ),
        }
        for card in cards
    ]
    return sorted(
        normalized,
        key=lambda card: (str(card.get("name")), bool(card.get("upgraded"))),
    )


def _player(
    player: dict[str, Any], *, include_combat: bool = False
) -> dict[str, Any]:
    result = {
        "hp": _number(player.get("hp")),
        "max_hp": _number(player.get("max_hp")),
        "gold": _number(player.get("gold")),
        "relics": sorted(
            relic.get("name")
            for relic in player.get("relics", [])
            if relic.get("name")
        ),
        "potions": sorted(
            potion.get("name")
            for potion in player.get("potions", [])
            if potion.get("name")
        ),
    }
    if include_combat:
        result["block"] = _number(player.get("block"))
    return result


def _standalone_context(state: dict[str, Any]) -> dict[str, Any]:
    context = state.get("context", {})
    return {
        "act": state.get("act", context.get("act")),
        "floor": state.get("floor", context.get("floor")),
    }


def _godot_context(state: dict[str, Any]) -> dict[str, Any]:
    run = state.get("run", {})
    return {"act": run.get("act"), "floor": run.get("floor")}


def normalize_standalone(state: dict[str, Any]) -> dict[str, Any]:
    phase = standalone_phase(state)
    result: dict[str, Any] = {
        "phase": phase,
        "context": _standalone_context(state),
        "player": _player(state.get("player", {}), include_combat=phase == "combat"),
    }
    if phase == "event":
        result["event"] = {
            "name": state.get("event_name"),
            "options": [
                {
                    "title": option.get("title"),
                    "locked": bool(option.get("is_locked", False)),
                }
                for option in state.get("options", [])
            ],
        }
    elif phase == "map":
        result["choices"] = sorted(
            (
                option.get("col"),
                option.get("row"),
                option.get("type"),
            )
            for option in state.get("choices", [])
        )
    elif phase == "combat":
        result["combat"] = {
            "round": _number(state.get("round")),
            "energy": _number(state.get("energy")),
            "hand": [_card(card) for card in state.get("hand", [])],
            "enemies": [
                {
                    "name": enemy.get("name"),
                    "hp": _number(enemy.get("hp")),
                    "max_hp": _number(enemy.get("max_hp")),
                    "block": _number(enemy.get("block")),
                }
                for enemy in state.get("enemies", [])
            ],
            "draw": _pile(state.get("draw_pile", [])),
            "discard": _pile(state.get("discard_pile", [])),
            "exhaust": _pile(state.get("exhaust_pile", [])),
        }
    elif phase == "card_reward":
        result["cards"] = [_card(card) for card in state.get("cards", [])]
    elif phase == "rest_site":
        result["options"] = [
            option.get("option_id") or option.get("name")
            for option in state.get("options", [])
            if option.get("is_enabled", True)
        ]
    elif phase == "game_over":
        result["victory"] = bool(state.get("victory"))
    return result


def normalize_godot(state: dict[str, Any]) -> dict[str, Any]:
    phase = godot_phase(state)
    player = state.get("player", {})
    result: dict[str, Any] = {
        "phase": phase,
        "context": _godot_context(state),
        "player": _player(player, include_combat=phase == "combat"),
    }
    if phase == "event":
        event = state.get("event", {})
        result["event"] = {
            "name": event.get("event_name"),
            "options": [
                {
                    "title": option.get("title"),
                    "locked": bool(option.get("is_locked", False)),
                }
                for option in event.get("options", [])
            ],
        }
    elif phase == "map":
        result["choices"] = sorted(
            (
                option.get("col"),
                option.get("row"),
                option.get("type"),
            )
            for option in state.get("map", {}).get("next_options", [])
        )
    elif phase == "combat":
        battle = state.get("battle", {})
        result["combat"] = {
            "round": _number(battle.get("round")),
            "energy": _number(player.get("energy")),
            "hand": [_card(card) for card in player.get("hand", [])],
            "enemies": [
                {
                    "name": enemy.get("name"),
                    "hp": _number(enemy.get("hp")),
                    "max_hp": _number(enemy.get("max_hp")),
                    "block": _number(enemy.get("block")),
                }
                for enemy in battle.get("enemies", [])
            ],
            "draw": _pile(player.get("draw_pile", [])),
            "discard": _pile(player.get("discard_pile", [])),
            "exhaust": _pile(player.get("exhaust_pile", [])),
        }
    elif phase == "card_reward":
        reward = state.get("card_reward", state.get("cards", []))
        cards = (
            reward
            if isinstance(reward, list)
            else reward.get("cards", []) if isinstance(reward, dict) else []
        )
        result["cards"] = [_card(card) for card in cards]
    elif phase == "rest_site":
        rest = state.get("rest_site", state.get("rest", {}))
        result["options"] = [
            option.get("option_id") or option.get("name")
            for option in rest.get("options", [])
            if option.get("is_enabled", True)
        ]
    elif phase == "game_over":
        game_over = state.get("game_over", {})
        result["victory"] = bool(
            game_over.get("victory", player.get("hp", 0) > 0)
        )
    return result


def parity_diff(
    standalone_state: dict[str, Any], godot_state: dict[str, Any]
) -> dict[str, Any]:
    expected = normalize_standalone(standalone_state)
    actual = normalize_godot(godot_state)
    if expected == actual:
        return {}
    differences: dict[str, Any] = {}
    for key in sorted(set(expected) | set(actual)):
        if expected.get(key) != actual.get(key):
            differences[key] = {
                "standalone": expected.get(key),
                "godot": actual.get(key),
            }
    return differences


def _selected(items: list[dict[str, Any]], index: int, label: str) -> dict[str, Any]:
    if index < 0 or index >= len(items):
        raise ParityMappingError(f"{label} index {index} is out of range")
    return items[index]


def _match_index(
    expected: dict[str, Any],
    candidates: list[dict[str, Any]],
    *,
    keys: tuple[str, ...],
    label: str,
) -> int:
    expected_values = tuple(expected.get(key) for key in keys)
    matches = [
        index
        for index, candidate in enumerate(candidates)
        if tuple(candidate.get(key) for key in keys) == expected_values
    ]
    if not matches:
        raise ParityMappingError(
            f"No Godot {label} matches {dict(zip(keys, expected_values))}"
        )
    return matches[0]


def translate_standalone_action(
    standalone_state: dict[str, Any],
    command: dict[str, Any],
    godot_state: dict[str, Any],
) -> dict[str, Any]:
    action = command.get("action")
    arguments = command.get("args", {})
    phase = standalone_phase(standalone_state)
    if phase != godot_phase(godot_state):
        raise ParityMappingError(
            f"phase mismatch: standalone={phase}, godot={godot_phase(godot_state)}"
        )
    if action == "choose_option" and phase == "event":
        expected = _selected(
            standalone_state.get("options", []),
            int(arguments["option_index"]),
            "event option",
        )
        options = godot_state.get("event", {}).get("options", [])
        index = _match_index(
            expected, options, keys=("title",), label="event option"
        )
        return {"action": "choose_event_option", "index": options[index]["index"]}
    if action == "choose_option" and phase == "rest_site":
        expected = _selected(
            standalone_state.get("options", []),
            int(arguments["option_index"]),
            "rest option",
        )
        options = godot_state.get("rest_site", {}).get("options", [])
        match_keys = (
            ("option_id",)
            if expected.get("option_id") is not None
            else ("name",)
        )
        index = _match_index(
            expected, options, keys=match_keys, label="rest option"
        )
        return {"action": "choose_rest_option", "index": options[index]["index"]}
    if action == "select_map_node":
        options = godot_state.get("map", {}).get("next_options", [])
        expected = {
            "col": arguments.get("col"),
            "row": arguments.get("row"),
        }
        index = _match_index(
            expected, options, keys=("col", "row"), label="map node"
        )
        return {"action": "choose_map_node", "index": options[index]["index"]}
    if action == "play_card":
        standalone_cards = standalone_state.get("hand", [])
        requested_index = int(arguments["card_index"])
        expected = _selected(
            standalone_cards, requested_index, "hand card"
        )
        godot_cards = godot_state.get("player", {}).get("hand", [])
        expected_card = _card(expected)
        godot_card_views = [_card(card) for card in godot_cards]
        if (
            0 <= requested_index < len(godot_cards)
            and tuple(
                godot_card_views[requested_index].get(key)
                for key in ("name", "type", "upgraded")
            )
            == tuple(
                expected_card.get(key)
                for key in ("name", "type", "upgraded")
            )
        ):
            card_index = requested_index
        else:
            card_index = _match_index(
                expected_card,
                godot_card_views,
                keys=("name", "type", "upgraded"),
                label="hand card",
            )
        result: dict[str, Any] = {
            "action": "play_card",
            "card_index": godot_cards[card_index]["index"],
        }
        if "target_index" in arguments:
            expected_enemy = _selected(
                standalone_state.get("enemies", []),
                int(arguments["target_index"]),
                "enemy",
            )
            godot_enemies = godot_state.get("battle", {}).get("enemies", [])
            enemy_index = _match_index(
                expected_enemy,
                godot_enemies,
                keys=("name",),
                label="enemy",
            )
            result["target"] = godot_enemies[enemy_index]["entity_id"]
        return result
    if action == "end_turn":
        return {"action": "end_turn"}
    if action == "select_card_reward":
        expected = _selected(
            standalone_state.get("cards", []),
            int(arguments["card_index"]),
            "card reward",
        )
        reward = godot_state.get("card_reward", godot_state.get("cards", []))
        cards = (
            reward
            if isinstance(reward, list)
            else reward.get("cards", []) if isinstance(reward, dict) else []
        )
        expected_card = _card(expected)
        card_views = [_card(card) for card in cards]
        index = _match_index(
            expected_card,
            card_views,
            keys=("name", "type", "upgraded"),
            label="card reward",
        )
        return {"action": "select_card_reward", "card_index": index}
    if action == "skip_card_reward":
        return {"action": "skip_card_reward"}
    if action == "select_bundle":
        return {"action": "select_bundle", "index": int(arguments["bundle_index"])}
    if action == "select_cards":
        indices = [
            int(value)
            for value in str(arguments.get("indices", "")).split(",")
            if value != ""
        ]
        if len(indices) != 1:
            raise ParityMappingError(
                "Godot replay currently supports one out-of-combat card "
                "selection per standalone action"
            )
        return {"action": "select_card", "index": indices[0]}
    if action == "skip_select":
        return {"action": "cancel_selection"}
    if action == "leave_room":
        return {"action": "proceed"}
    if action == "proceed":
        return {"action": "proceed"}
    raise ParityMappingError(
        f"Unsupported standalone action {action!r} in phase {phase!r}"
    )


def automatic_reconciliation_action(
    expected_standalone_state: dict[str, Any],
    godot_state: dict[str, Any],
) -> dict[str, Any] | None:
    """Drive presentation-only Godot states toward the next source decision."""
    expected_phase = standalone_phase(expected_standalone_state)
    phase = godot_phase(godot_state)
    if phase == "event" and expected_phase != "event":
        options = godot_state.get("event", {}).get("options", [])
        available = [
            option for option in options if not option.get("is_locked", False)
        ]
        proceed = [option for option in available if option.get("is_proceed")]
        if len(proceed) == 1:
            return {
                "action": "choose_event_option",
                "index": proceed[0]["index"],
            }
    if phase == "card_select" and expected_phase != "card_select":
        selection = godot_state.get("card_select", {})
        if selection.get("can_confirm"):
            return {"action": "confirm_selection"}
    if phase == "bundle_select" and expected_phase != "bundle_select":
        selection = godot_state.get("bundle_select", {})
        if selection.get("preview_showing") and selection.get("can_confirm"):
            return {"action": "confirm_bundle_selection"}
    if phase == "rewards":
        rewards = godot_state.get("rewards", {})
        items = rewards.get("items", []) if isinstance(rewards, dict) else []
        non_card = [item for item in items if item.get("type") != "card"]
        if non_card:
            return {
                "action": "claim_reward",
                "index": non_card[0].get("index", 0),
            }
        card_rewards = [item for item in items if item.get("type") == "card"]
        if expected_phase == "card_reward" and card_rewards:
            return {
                "action": "claim_reward",
                "index": card_rewards[0].get("index", 0),
            }
        if expected_phase != "card_reward" and rewards.get("can_proceed", True):
            return {"action": "proceed"}
    if phase == "rest_site" and expected_phase != "rest_site":
        rest = godot_state.get("rest_site", {})
        if rest.get("can_proceed"):
            return {"action": "proceed"}
    return None


def multiset_delta(left: list[str], right: list[str]) -> dict[str, int]:
    """Small diagnostic helper for future pile/deck parity reports."""
    return dict(Counter(left) - Counter(right))
