#!/usr/bin/env python3
"""Smoke test: random agent against STS2MCP REST API.

Usage:
    1. Launch STS2 with STS2_MCP mod installed
    2. Start a singleplayer run manually in-game
    3. Run this script: uv run python test_sts2mcp_random.py
    4. Watch the random agent play!
"""

import json
import logging
import random
import sys
import time
import urllib.request
import urllib.error

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s: %(message)s",
)
logger = logging.getLogger("test_sts2mcp")

BASE_URL = "http://127.0.0.1:15526/api/v1/singleplayer"


def get_state() -> dict:
    req = urllib.request.Request(f"{BASE_URL}?format=json")
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())


def post_action(action: dict) -> dict:
    data = json.dumps(action).encode()
    req = urllib.request.Request(
        BASE_URL,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())


def pick_random_action(state: dict) -> dict | None:
    state_type = state.get("state_type", "unknown")

    if state_type in ("monster", "elite", "boss"):
        return pick_combat_action(state)
    elif state_type == "combat_card_select":
        return pick_combat_card_select_action(state)
    elif state_type == "map":
        return pick_map_action(state)
    elif state_type == "card_reward":
        return pick_card_reward_action(state)
    elif state_type == "rewards":
        return pick_rewards_action(state)
    elif state_type == "event":
        return pick_event_action(state)
    elif state_type == "rest_site":
        return pick_rest_action(state)
    elif state_type in ("shop", "merchant"):
        return pick_shop_action(state)
    elif state_type == "card_select":
        return pick_card_select_action(state)
    elif state_type == "treasure_relic":
        return pick_treasure_action(state)
    elif state_type == "menu":
        logger.info("At menu — start a run manually in-game")
        return None
    elif state_type == "game_over":
        logger.info("Game over!")
        return None
    else:
        logger.info(f"Unknown state type: {state_type}, trying proceed")
        return {"action": "proceed"}


def pick_combat_action(state: dict) -> dict:
    player = state.get("player", {})
    hand = player.get("hand", [])
    potions = player.get("potions", [])
    battle = state.get("battle", {})

    # Only act during play phase
    if not battle.get("is_play_phase", False):
        return None  # type: ignore[return-value]

    # Try to play a random playable card
    playable = [c for c in hand if c.get("can_play", False)]
    if playable and random.random() > 0.2:
        card = random.choice(playable)
        action: dict = {"action": "play_card", "card_index": card["index"]}
        if card.get("target_type") == "AnyEnemy":
            enemies = battle.get("enemies", [])
            alive = [e for e in enemies if e.get("hp", 0) > 0]
            if alive:
                action["target"] = random.choice(alive)["entity_id"]
        return action

    # Occasionally use a potion
    usable_potions = [p for p in potions if p.get("id") and p.get("id") != "empty"]
    if usable_potions and random.random() < 0.1:
        potion = random.choice(usable_potions)
        action = {"action": "use_potion", "slot": potion.get("slot", 0)}
        if potion.get("target_type") == "AnyEnemy":
            enemies = battle.get("enemies", [])
            alive = [e for e in enemies if e.get("hp", 0) > 0]
            if alive:
                action["target"] = random.choice(alive)["entity_id"]
        return action

    return {"action": "end_turn"}


def pick_combat_card_select_action(state: dict) -> dict:
    # Select a random card if prompted, then confirm
    cards = state.get("selectable_cards", state.get("cards", []))
    if cards:
        selected = [c for c in cards if c.get("is_selected")]
        if not selected:
            return {"action": "combat_select_card", "card_index": random.randint(0, len(cards) - 1)}
    return {"action": "combat_confirm_selection"}


def pick_map_action(state: dict) -> dict:
    next_options = state.get("next_options", state.get("map", {}).get("next_options", []))
    if next_options:
        return {"action": "choose_map_node", "index": random.randint(0, len(next_options) - 1)}
    return {"action": "proceed"}


def pick_card_reward_action(state: dict) -> dict:
    reward_data = state.get("card_reward", state.get("cards", state.get("card_options", [])))
    cards = reward_data if isinstance(reward_data, list) else reward_data.get("cards", []) if isinstance(reward_data, dict) else []
    if cards:
        return {"action": "select_card_reward", "card_index": random.randint(0, len(cards) - 1)}
    return {"action": "skip_card_reward"}


def pick_rewards_action(state: dict) -> dict:
    rewards_data = state.get("rewards", {})
    items = rewards_data.get("items", []) if isinstance(rewards_data, dict) else []
    can_proceed = rewards_data.get("can_proceed", True) if isinstance(rewards_data, dict) else True
    # Claim non-card rewards, skip card rewards (handle those in card_reward state)
    non_card = [r for r in items if r.get("type") != "card"]
    if non_card:
        return {"action": "claim_reward", "index": non_card[0].get("index", 0)}
    return {"action": "proceed"}


def pick_event_action(state: dict) -> dict:
    options = state.get("options", state.get("event", {}).get("options", []))
    available = [o for o in options if not o.get("is_locked", False)]
    if available:
        return {"action": "choose_event_option", "index": random.randint(0, len(available) - 1)}
    return {"action": "proceed"}


def pick_rest_action(state: dict) -> dict:
    options = state.get("options", state.get("rest_options", []))
    if options:
        return {"action": "choose_rest_option", "index": random.randint(0, len(options) - 1)}
    return {"action": "proceed"}


def pick_shop_action(state: dict) -> dict:
    # Just leave the shop
    return {"action": "proceed"}


def pick_card_select_action(state: dict) -> dict:
    cards = state.get("cards", [])
    selected = [c for c in cards if c.get("is_selected")]
    if not selected and cards:
        return {"action": "select_card", "index": random.randint(0, len(cards) - 1)}
    return {"action": "confirm_selection"}


def pick_treasure_action(state: dict) -> dict:
    relics = state.get("relics", [])
    if relics:
        return {"action": "claim_treasure_relic", "index": 0}
    return {"action": "proceed"}


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 15526
    global BASE_URL
    BASE_URL = f"http://127.0.0.1:{port}/api/v1/singleplayer"

    logger.info(f"Connecting to STS2MCP at {BASE_URL}")

    step = 0
    last_state_type = None
    errors_in_a_row = 0

    while True:
        try:
            state = get_state()
            errors_in_a_row = 0
        except urllib.error.URLError as e:
            errors_in_a_row += 1
            if errors_in_a_row > 5:
                logger.error("Can't reach STS2MCP, is the game running with the mod?")
                return
            logger.warning(f"Connection error: {e}, retrying...")
            time.sleep(2)
            continue

        state_type = state.get("state_type", "unknown")
        player = state.get("player", {})
        hp = player.get("hp", "?")
        run = state.get("run", {})
        floor = run.get("floor", "?")

        if state_type != last_state_type:
            logger.info(f"State: {state_type} | HP={hp} Floor={floor}")
            last_state_type = state_type

        if state_type == "menu":
            logger.info("Waiting for run to start (start one manually in-game)...")
            time.sleep(3)
            continue

        action = pick_random_action(state)
        if action is None:
            time.sleep(0.5)
            continue

        step += 1
        try:
            result = post_action(action)
            status = result.get("status", "?")
            if status != "ok":
                msg = result.get("error", result.get("message", status))
                logger.warning(f"Step {step}: {action.get('action')} -> {msg}")
                time.sleep(0.3)
            else:
                logger.info(f"Step {step}: {action.get('action')} -> ok | HP={hp} Floor={floor}")
                time.sleep(0.5)  # let the game settle
        except urllib.error.HTTPError as e:
            body = e.read().decode() if e.fp else ""
            logger.warning(f"Step {step}: {action.get('action')} -> HTTP {e.code}: {body[:100]}")
            time.sleep(0.3)
        except Exception as e:
            logger.warning(f"Step {step}: {action.get('action')} -> error: {e}")
            time.sleep(0.3)


if __name__ == "__main__":
    main()
