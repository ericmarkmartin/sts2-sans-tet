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
    elif state_type in ("combat_card_select", "hand_select"):
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
        return pick_menu_action(state)
    elif state_type == "game_over":
        return pick_game_over_action(state)
    elif state_type == "overlay":
        return pick_overlay_action(state)
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
    select_data = state.get("hand_select", state.get("combat_card_select", {}))
    cards = select_data.get("cards", [])
    if not cards:
        return {"action": "combat_confirm_selection"}
    # Check if we can confirm (card already selected)
    if select_data.get("can_confirm"):
        return {"action": "combat_confirm_selection"}
    return {"action": "combat_select_card", "card_index": random.randint(0, len(cards) - 1)}


def pick_map_action(state: dict) -> dict:
    map_data = state.get("map", {})
    next_options = map_data.get("next_options", [])
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
    event = state.get("event", {})
    options = event.get("options", [])
    available = [o for o in options if not o.get("is_locked", False)]
    if available:
        return {"action": "choose_event_option", "index": available[random.randint(0, len(available) - 1)].get("index", 0)}
    return {"action": "proceed"}


def pick_rest_action(state: dict) -> dict:
    rest_data = state.get("rest_site", state.get("rest", {}))
    options = rest_data.get("options", []) if isinstance(rest_data, dict) else []
    if options:
        return {"action": "choose_rest_option", "index": random.randint(0, len(options) - 1)}
    return {"action": "proceed"}


def pick_shop_action(state: dict) -> dict:
    # Just leave the shop
    return {"action": "proceed"}


def pick_card_select_action(state: dict) -> dict:
    card_select = state.get("card_select", {})
    cards = card_select.get("cards", [])
    if not cards:
        return {"action": "confirm_selection"}
    if card_select.get("can_confirm"):
        return {"action": "confirm_selection"}
    return {"action": "select_card", "index": random.randint(0, len(cards) - 1)}


def pick_menu_action(state: dict) -> dict | None:
    menu = state.get("menu", {})
    screen = menu.get("screen", "unknown")

    if screen == "character_select":
        characters = menu.get("characters", [])
        unlocked = [c for c in characters if not c.get("is_locked", True)]
        can_confirm = menu.get("can_confirm", False)

        if can_confirm:
            logger.info("Menu: confirming character")
            return {"action": "confirm_character"}
        elif unlocked:
            char = random.choice(unlocked)
            logger.info(f"Menu: selecting character {char.get('id')}")
            return {"action": "select_character", "character": char.get("id", "0")}
        return None

    elif screen == "singleplayer_submenu":
        logger.info("Menu: clicking standard run")
        return {"action": "click_standard"}

    elif screen == "timeline":
        if menu.get("inspect_screen_open"):
            logger.info("Menu: closing timeline inspect screen")
            return {"action": "reveal_epoch"}  # will close inspect screen first
        elif menu.get("pending_reveals", 0) > 0:
            logger.info(f"Menu: revealing epoch ({menu.get('pending_reveals')} pending)")
            return {"action": "reveal_epoch"}
        elif menu.get("has_back"):
            logger.info("Menu: done with timeline, going back")
            return {"action": "timeline_back"}
        else:
            logger.info("Menu: on timeline, waiting...")
            return None

    elif screen == "modal":
        logger.info("Menu: dismissing modal dialog")
        return {"action": "dismiss_screen"}

    elif screen == "main_menu":
        can_start = menu.get("can_start_run", True)
        if menu.get("has_run_to_abandon"):
            logger.info("Menu: abandoning existing run")
            return {"action": "abandon_run"}
        elif can_start:
            logger.info("Menu: clicking singleplayer")
            return {"action": "click_singleplayer"}
        elif menu.get("has_timeline"):
            logger.info("Menu: can't start run, opening timeline for unlocks")
            return {"action": "click_timeline"}
        else:
            logger.info("Menu: singleplayer blocked, trying dismiss")
            return {"action": "dismiss_screen"}

    elif screen == "loading":
        return None  # wait for menu to finish loading

    else:
        logger.info(f"Menu: unknown screen '{screen}', trying dismiss")
        return {"action": "dismiss_screen"}


def pick_overlay_action(state: dict) -> dict | None:
    overlay = state.get("overlay", {})
    screen_type = overlay.get("screen_type", "")
    logger.info(f"Overlay: {screen_type}, trying proceed")
    return {"action": "proceed"}


def pick_game_over_action(state: dict) -> dict:
    game_over = state.get("game_over", {})
    if game_over.get("main_menu_available"):
        logger.info("Game over — returning to main menu")
        return {"action": "game_over_main_menu"}
    elif game_over.get("continue_available"):
        logger.info("Game over — clicking continue")
        return {"action": "game_over_continue"}
    else:
        # Buttons not ready yet, wait
        return None  # type: ignore[return-value]


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
    stuck_count = 0
    last_state_sig = None  # signature for stuck detection
    episode = 0

    # Fallback actions to try when stuck
    FALLBACK_ACTIONS = [
        {"action": "dismiss_screen"},
        {"action": "proceed"},
        {"action": "confirm_selection"},
        {"action": "combat_confirm_selection"},
        {"action": "skip_card_reward"},
        {"action": "cancel_selection"},
        {"action": "end_turn"},
    ]

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

        # First try the normal action picker
        action = pick_random_action(state)

        if action is None:
            time.sleep(0.5)
            continue

        # Stuck detection: track state signature across actions
        state_sig = f"{state_type}:{hp}:{floor}:{state.get('menu', {}).get('screen', '')}:{state.get('overlay', {}).get('screen_type', '')}"
        if state_sig == last_state_sig:
            stuck_count += 1
        else:
            stuck_count = 0
            last_state_sig = state_sig

        # If stuck for too many steps, override with fallback actions
        if stuck_count > 10:
            fallback_idx = (stuck_count - 11) % len(FALLBACK_ACTIONS)
            action = FALLBACK_ACTIONS[fallback_idx]
            logger.warning(f"Stuck for {stuck_count} steps on {state_type}, trying fallback: {action.get('action')}")

        step += 1
        try:
            result = post_action(action)
            status = result.get("status", "?")
            if status != "ok":
                msg = result.get("error", result.get("message", status))
                if stuck_count <= 8:  # don't spam warnings during fallback
                    logger.warning(f"Step {step}: {action.get('action')} -> {msg}")
                time.sleep(0.3)
            else:
                logger.info(f"Step {step}: {action.get('action')} -> ok | HP={hp} Floor={floor}")
                stuck_count = 0  # successful action resets stuck counter
                time.sleep(0.5)
        except urllib.error.HTTPError as e:
            body = e.read().decode() if e.fp else ""
            logger.warning(f"Step {step}: {action.get('action')} -> HTTP {e.code}: {body[:100]}")
            time.sleep(0.3)
        except Exception as e:
            logger.warning(f"Step {step}: {action.get('action')} -> error: {e}")
            time.sleep(0.3)


if __name__ == "__main__":
    main()
