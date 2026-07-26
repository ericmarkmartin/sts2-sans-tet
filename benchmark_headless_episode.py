#!/usr/bin/env python3
"""Run and trace one directly-bootstrapped Godot-headless combat."""

from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import os
import random
import re
import socket
import subprocess
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_GAME = Path(
    "/mnt/c/Program Files (x86)/Steam/steamapps/common/"
    "Slay the Spire 2/SlayTheSpire2.exe"
)


class Bridge:
    def __init__(self, port: int) -> None:
        self._connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)

    def request(self, method: str, path: str, body: dict[str, Any] | None = None) -> dict:
        encoded = json.dumps(body, separators=(",", ":")) if body is not None else None
        headers = {"Content-Type": "application/json"} if encoded is not None else {}
        self._connection.request(method, path, body=encoded, headers=headers)
        response = self._connection.getresponse()
        payload = response.read()
        if response.status >= 400:
            raise RuntimeError(f"HTTP {response.status}: {payload.decode(errors='replace')}")
        return json.loads(payload)

    def close(self) -> None:
        self._connection.close()


def combat_signature(state: dict[str, Any]) -> str:
    player = state.get("player", {})
    battle = state.get("battle", {})
    compact = {
        "state_type": state.get("state_type"),
        "round": battle.get("round"),
        "play": battle.get("is_play_phase"),
        "hp": player.get("hp"),
        "energy": player.get("energy"),
        "hand": [
            (card.get("id"), card.get("cost"), card.get("can_play"))
            for card in player.get("hand", [])
        ],
        "enemies": [
            (enemy.get("entity_id"), enemy.get("hp"), enemy.get("block"))
            for enemy in battle.get("enemies", [])
        ],
    }
    return json.dumps(compact, sort_keys=True, separators=(",", ":"))


def choose_action(state: dict[str, Any], rng: random.Random) -> dict[str, Any] | None:
    battle = state.get("battle", {})
    if not battle.get("is_play_phase"):
        return None
    playable = [card for card in state.get("player", {}).get("hand", []) if card.get("can_play")]
    if playable and rng.random() >= 0.2:
        card = rng.choice(playable)
        action: dict[str, Any] = {"action": "play_card", "card_index": card["index"]}
        if card.get("target_type") == "AnyEnemy":
            enemies = [enemy for enemy in battle.get("enemies", []) if enemy.get("hp", 0) > 0]
            if not enemies:
                return {"action": "end_turn"}
            action["target"] = rng.choice(enemies)["entity_id"]
        return action
    return {"action": "end_turn"}


def _first_number(text: Any, pattern: str) -> int:
    match = re.search(pattern, str(text or ""), re.IGNORECASE)
    return int(match.group(1)) if match else 0


def choose_tactical_combat_action(state: dict[str, Any]) -> dict[str, Any] | None:
    """A conservative deterministic policy for ordinary Ironclad combats."""
    battle = state.get("battle", {})
    if not battle.get("is_play_phase"):
        return None
    player = state.get("player", {})
    playable = [card for card in player.get("hand", []) if card.get("can_play")]
    if not playable:
        return {"action": "end_turn"}

    enemies = [enemy for enemy in battle.get("enemies", []) if enemy.get("hp", 0) > 0]
    incoming_by_enemy: dict[Any, int] = {}
    for enemy in enemies:
        incoming_by_enemy[enemy.get("entity_id")] = sum(
            _first_number(intent.get("label"), r"(\d+)")
            for intent in enemy.get("intents", [])
            if intent.get("type") == "Attack"
        )
    incoming = sum(incoming_by_enemy.values())
    block_needed = max(0, incoming - int(player.get("block") or 0))

    attacks: list[tuple[dict[str, Any], int]] = []
    blocks: list[tuple[dict[str, Any], int]] = []
    for card in playable:
        description = card.get("description", "")
        damage = _first_number(description, r"Deal\s+(\d+)\s+damage")
        block = _first_number(description, r"Gain\s+(\d+)\s+Block")
        if damage:
            attacks.append((card, damage))
        if block:
            blocks.append((card, block))

    # Remove incoming damage immediately when a playable attack is lethal.
    lethal: list[tuple[int, int, dict[str, Any], dict[str, Any]]] = []
    for card, damage in attacks:
        for enemy in enemies:
            effective_hp = int(enemy.get("hp") or 0) + int(enemy.get("block") or 0)
            if damage >= effective_hp:
                lethal.append(
                    (
                        incoming_by_enemy.get(enemy.get("entity_id"), 0),
                        -effective_hp,
                        card,
                        enemy,
                    )
                )
    if lethal:
        _, _, card, enemy = max(lethal, key=lambda item: (item[0], item[1]))
        action = {"action": "play_card", "card_index": card["index"]}
        if card.get("target_type") == "AnyEnemy":
            action["target"] = enemy["entity_id"]
        return action

    # Cover telegraphed damage before spending energy on nonlethal attacks.
    if block_needed and blocks:
        card, _ = max(blocks, key=lambda item: (item[1], -int(item[0].get("index", 0))))
        return {"action": "play_card", "card_index": card["index"]}

    if attacks and enemies:
        # Bash is efficient early against a durable target; otherwise maximize damage.
        bash = next(
            (
                pair
                for pair in attacks
                if pair[0].get("id") == "BASH"
                or pair[0].get("name", "").lower() == "bash"
            ),
            None,
        )
        card, damage = bash or max(attacks, key=lambda item: item[1])
        target = max(
            enemies,
            key=lambda enemy: (
                int(enemy.get("hp") or 0) + int(enemy.get("block") or 0),
                incoming_by_enemy.get(enemy.get("entity_id"), 0),
            ),
        )
        action = {"action": "play_card", "card_index": card["index"]}
        if card.get("target_type") == "AnyEnemy":
            action["target"] = target["entity_id"]
        return action

    # Play useful zero/low-cost non-attacks before ending the turn.
    non_attacks = [card for card in playable if card.get("type") != "Attack"]
    if non_attacks:
        card = min(non_attacks, key=lambda item: int(item.get("index", 0)))
        return {"action": "play_card", "card_index": card["index"]}
    return {"action": "end_turn"}


def choose_full_run_action(
    state: dict[str, Any], rng: random.Random
) -> dict[str, Any] | None:
    state_type = state.get("state_type")
    if state_type in {"monster", "elite", "boss"}:
        return choose_tactical_combat_action(state)
    if state_type in {"combat_card_select", "hand_select"}:
        selection = state.get("hand_select", state.get("combat_card_select", {}))
        cards = selection.get("cards", [])
        if selection.get("can_confirm") or not cards:
            return {"action": "combat_confirm_selection"}
        return {"action": "combat_select_card", "card_index": rng.randrange(len(cards))}
    if state_type == "map":
        options = state.get("map", {}).get("next_options", [])
        if options:
            # Avoid elites, prefer healing when hurt, then unknown/shop nodes.
            hp = state.get("player", {}).get("hp", 0)
            max_hp = state.get("player", {}).get("max_hp", 1)
            priorities = (
                {"RestSite": 0, "Unknown": 1, "Shop": 2, "Monster": 3, "Elite": 4}
                if hp < max_hp * 0.65
                else {"Unknown": 0, "Shop": 1, "Monster": 2, "RestSite": 3, "Elite": 4}
            )
            choice = min(
                options,
                key=lambda option: (
                    priorities.get(option.get("type"), 3),
                    option.get("index", 0),
                ),
            )
            return {"action": "choose_map_node", "index": choice.get("index", 0)}
        return {"action": "proceed"}
    if state_type == "card_reward":
        reward = state.get(
            "card_reward", state.get("cards", state.get("card_options", []))
        )
        cards = (
            reward
            if isinstance(reward, list)
            else reward.get("cards", []) if isinstance(reward, dict) else []
        )
        if cards:
            return {"action": "select_card_reward", "card_index": rng.randrange(len(cards))}
        return {"action": "skip_card_reward"}
    if state_type == "rewards":
        rewards = state.get("rewards", {})
        items = rewards.get("items", []) if isinstance(rewards, dict) else []
        non_card = [item for item in items if item.get("type") != "card"]
        if non_card:
            return {
                "action": "claim_reward",
                "index": non_card[0].get("index", 0),
            }
        return {"action": "proceed"}
    if state_type == "event":
        options = state.get("event", {}).get("options", [])
        available = [option for option in options if not option.get("is_locked", False)]
        if available:
            return {
                "action": "choose_event_option",
                "index": rng.choice(available).get("index", 0),
            }
        return {"action": "advance_dialogue"}
    if state_type == "rest_site":
        rest = state.get("rest_site", state.get("rest", {}))
        options = rest.get("options", []) if isinstance(rest, dict) else []
        if options:
            hp = state.get("player", {}).get("hp", 0)
            max_hp = state.get("player", {}).get("max_hp", 1)
            if hp < max_hp * 0.75:
                heal = next(
                    (
                        option
                        for option in options
                        if any(
                            word in str(option).lower()
                            for word in ("rest", "heal", "sleep")
                        )
                    ),
                    options[0],
                )
                return {"action": "choose_rest_option", "index": heal.get("index", 0)}
            return {"action": "choose_rest_option", "index": options[0].get("index", 0)}
        return {"action": "proceed"}
    if state_type in {"shop", "merchant"}:
        return {"action": "proceed"}
    if state_type == "card_select":
        selection = state.get("card_select", {})
        cards = selection.get("cards", [])
        if selection.get("can_confirm") or not cards:
            return {"action": "confirm_selection"}
        return {"action": "select_card", "index": rng.randrange(len(cards))}
    if state_type == "treasure_relic":
        relics = state.get("relics", [])
        if relics:
            return {"action": "claim_treasure_relic", "index": 0}
        return {"action": "proceed"}
    if state_type in {"game_over", "menu"}:
        return None
    if state_type == "overlay":
        return {"action": "proceed"}
    return {"action": "proceed"}


def state_signature(state: dict[str, Any]) -> str:
    return json.dumps(state, sort_keys=True, separators=(",", ":"))


def jsonl_line(file: Any, payload: Any) -> None:
    file.write(json.dumps(payload, separators=(",", ":")) + "\n")
    file.flush()


def powershell_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def archive_combat_replay(
    source: Path,
    replay_dir: Path,
    combat_index: int,
    fresh_after_wall: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + 5
    while True:
        if (
            source.exists()
            and source.stat().st_size > 0
            and source.stat().st_mtime >= fresh_after_wall - 1
        ):
            break
        if time.monotonic() >= deadline:
            raise RuntimeError(f"Fresh combat replay did not appear at {source}")
        time.sleep(0.01)

    replay_name = f"combat-{combat_index:03d}.mcr"
    replay_path = replay_dir / replay_name
    shutil.copy2(source, replay_path)
    replay_bytes = replay_path.read_bytes()
    return {
        "combat_index": combat_index,
        "path": str(Path("replays") / replay_name),
        "size": len(replay_bytes),
        "sha256": hashlib.sha256(replay_bytes).hexdigest(),
    }


def allocate_episode_dir(root: Path, explicit: Path | None) -> Path:
    if explicit is not None:
        explicit.mkdir(parents=True, exist_ok=True)
        if any(explicit.iterdir()):
            raise RuntimeError(f"Episode directory is not empty: {explicit}")
        return explicit
    root.mkdir(parents=True, exist_ok=True)
    for index in range(1, 1_000_000):
        candidate = root / f"episode-{index:04d}"
        try:
            candidate.mkdir()
            return candidate
        except FileExistsError:
            continue
    raise RuntimeError(f"Could not allocate an episode directory under {root}")


def sha256_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def game_version_metadata(game_log_path: Path) -> dict[str, str | None]:
    text = game_log_path.read_text(encoding="utf-8", errors="replace")

    def value(label: str) -> str | None:
        match = re.search(rf"^{re.escape(label)}:\s*(.+)$", text, re.MULTILINE)
        return match.group(1).strip() if match else None

    return {
        "release_version": value("Release Version"),
        "release_commit": value("Release Commit"),
        "engine_version": value("Engine Version"),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--game", type=Path, default=DEFAULT_GAME)
    parser.add_argument("--port", type=int, default=15526)
    parser.add_argument("--seed", default="HEADLESSBENCH")
    parser.add_argument("--policy-seed", type=int, default=0)
    parser.add_argument("--max-actions", type=int, default=200)
    parser.add_argument(
        "--full-run",
        action="store_true",
        help="Start at act entry and drive all run states until game over",
    )
    parser.add_argument("--warm-resets", type=int, default=0)
    parser.add_argument("--startup-timeout", type=float, default=60)
    parser.add_argument("--episodes-dir", type=Path, default=Path("headless/episodes"))
    parser.add_argument("--episode-dir", type=Path)
    parser.add_argument(
        "--mcr-source",
        type=Path,
        help="Profile-scoped replays/latest.mcr to archive after combat",
    )
    args = parser.parse_args()
    if args.full_run and args.warm_resets:
        parser.error("--warm-resets is only supported by the fixed-combat benchmark")

    episode_dir = allocate_episode_dir(args.episodes_dir, args.episode_dir)
    replay_dir = episode_dir / "replays"
    replay_dir.mkdir()
    game_log_path = episode_dir / "game.log"
    with socket.socket() as probe:
        probe.settimeout(0.2)
        if probe.connect_ex(("127.0.0.1", args.port)) == 0:
            raise RuntimeError(
                f"Port {args.port} is already accepting connections; "
                "stop the existing bridge before starting a benchmark"
            )

    environment = os.environ.copy()
    environment["STS2_BOOTSTRAP_SEED"] = args.seed
    environment["STS2_BOOTSTRAP_MODE"] = "full" if args.full_run else "combat"
    game_args = [
        "--headless",
        "--audio-driver",
        "Dummy",
        "--bootstrap",
    ]
    command = [str(args.game), *game_args]
    pid_path = (episode_dir / ".game.pid").resolve()
    pid_path.unlink(missing_ok=True)
    windows_game_path = subprocess.check_output(
        ["wslpath", "-w", str(args.game)], text=True
    ).strip()
    windows_pid_path = subprocess.check_output(
        ["wslpath", "-w", str(pid_path)], text=True
    ).strip()
    launch_script = (
        f"$env:STS2_BOOTSTRAP_SEED={powershell_literal(args.seed)}; "
        f"$env:STS2_BOOTSTRAP_MODE={powershell_literal(environment['STS2_BOOTSTRAP_MODE'])}; "
        f"$p=Start-Process -FilePath {powershell_literal(windows_game_path)} "
        f"-ArgumentList @({','.join(powershell_literal(arg) for arg in game_args)}) "
        "-NoNewWindow -PassThru; "
        f"[IO.File]::WriteAllText({powershell_literal(windows_pid_path)},[string]$p.Id); "
        "$p.WaitForExit(); exit $p.ExitCode"
    )
    launcher_command = [
        "powershell.exe",
        "-NoProfile",
        "-Command",
        launch_script,
    ]
    game_log = game_log_path.open("wb")
    process = subprocess.Popen(
        launcher_command,
        cwd=args.game.parent,
        env=environment,
        stdout=game_log,
        stderr=subprocess.STDOUT,
    )
    started = time.monotonic()
    started_wall = time.time()
    bridge = Bridge(args.port)
    rng = random.Random(args.policy_seed)
    latencies: list[float] = []

    started_at_utc = datetime.now(timezone.utc).isoformat()
    try:
        with (
            (episode_dir / "actions.jsonl").open("w", encoding="utf-8") as actions_file,
            (episode_dir / "results.jsonl").open("w", encoding="utf-8") as results_file,
        ):
            deadline = time.monotonic() + args.startup_timeout
            state: dict[str, Any] | None = None
            while time.monotonic() < deadline and process.poll() is None:
                try:
                    candidate = bridge.request("GET", "/api/v1/singleplayer")
                    state_type = candidate.get("state_type")
                    fixed_combat_ready = (
                        state_type in {"monster", "elite", "boss"}
                        and candidate.get("battle", {}).get("is_play_phase")
                    )
                    full_run_ready = args.full_run and state_type not in {
                        None,
                        "unknown",
                        "menu",
                    }
                    if fixed_combat_ready or full_run_ready:
                        state = candidate
                        break
                except (OSError, RuntimeError, json.JSONDecodeError):
                    bridge.close()
                    bridge = Bridge(args.port)
                time.sleep(0.01)
            if state is None:
                exit_detail = (
                    f"game exited with code {process.returncode}"
                    if process.returncode is not None
                    else "game was still running"
                )
                raise RuntimeError(
                    f"Run did not become ready within {args.startup_timeout:g} seconds; "
                    f"{exit_detail}; see {game_log_path}"
                )

            (episode_dir / "initial.state").write_text(
                json.dumps(state, indent=2) + "\n",
                encoding="utf-8",
            )
            initial_state = state
            initial_hp = state.get("player", {}).get("hp")
            actions = 0
            replay_archives: list[dict[str, Any]] = []
            combat_index = 0
            combat_started_wall = (
                started_wall
                if state.get("state_type") in {"monster", "elite", "boss"}
                else None
            )
            consecutive_action_errors = 0
            while actions < args.max_actions:
                state_type = state.get("state_type")
                if state_type == "game_over":
                    break
                if not args.full_run and state_type not in {
                    "monster",
                    "elite",
                    "boss",
                    "combat_card_select",
                    "hand_select",
                }:
                    break

                action = (
                    choose_full_run_action(state, rng)
                    if args.full_run
                    else choose_action(state, rng)
                )
                if action is None:
                    time.sleep(0.005)
                    candidate = bridge.request("GET", "/api/v1/singleplayer")
                    if state_signature(candidate) != state_signature(state):
                        jsonl_line(
                            results_file,
                            {
                                "kind": "async_state",
                                "after_action_index": actions - 1 if actions else None,
                                "t": time.monotonic() - started,
                                "state": candidate,
                            },
                        )
                    if (
                        combat_started_wall is not None
                        and candidate.get("state_type")
                        not in {
                            "monster",
                            "elite",
                            "boss",
                            "combat_card_select",
                            "hand_select",
                        }
                    ):
                        if args.mcr_source is not None:
                            writer_result = bridge.request(
                                "POST",
                                "/api/v1/singleplayer",
                                {"action": "write_replay"},
                            )
                            replay_record = archive_combat_replay(
                                args.mcr_source,
                                replay_dir,
                                combat_index,
                                combat_started_wall,
                            )
                            replay_record["writer_result"] = writer_result
                            replay_archives.append(replay_record)
                        combat_index += 1
                        combat_started_wall = None
                    state = candidate
                    continue

                before = state_signature(state)
                previous_state_type = state_type
                action_started = time.monotonic()
                action_index = actions
                jsonl_line(
                    actions_file,
                    {
                        "index": action_index,
                        "t": action_started - started,
                        "action": action,
                    },
                )
                result = bridge.request("POST", "/api/v1/singleplayer", action)
                actions += 1
                if result.get("status") not in {"ok", "accepted"}:
                    consecutive_action_errors += 1
                    if consecutive_action_errors >= 20:
                        raise RuntimeError(
                            f"Twenty consecutive rejected actions; last was "
                            f"{action}: {result}"
                        )
                    time.sleep(0.01)
                    state = bridge.request("GET", "/api/v1/singleplayer")
                    jsonl_line(
                        results_file,
                        {
                            "kind": "action_result",
                            "index": action_index,
                            "t": time.monotonic() - started,
                            "result": result,
                            "state": state,
                        },
                    )
                    continue
                consecutive_action_errors = 0

                change_deadline = time.monotonic() + 10
                while True:
                    candidate = bridge.request("GET", "/api/v1/singleplayer")
                    if state_signature(candidate) != before:
                        state = candidate
                        break
                    if time.monotonic() >= change_deadline:
                        raise RuntimeError(f"State did not change after action {action}")
                    time.sleep(0.005)
                latencies.append(time.monotonic() - action_started)
                jsonl_line(
                    results_file,
                    {
                        "kind": "action_result",
                        "index": action_index,
                        "t": time.monotonic() - started,
                        "result": result,
                        "state": state,
                    },
                )

                new_state_type = state.get("state_type")
                if (
                    combat_started_wall is None
                    and new_state_type in {"monster", "elite", "boss"}
                ):
                    combat_started_wall = time.time()
                left_combat = (
                    combat_started_wall is not None
                    and previous_state_type
                    in {
                        "monster",
                        "elite",
                        "boss",
                        "combat_card_select",
                        "hand_select",
                    }
                    and new_state_type
                    not in {
                        "monster",
                        "elite",
                        "boss",
                        "combat_card_select",
                        "hand_select",
                    }
                )
                if left_combat:
                    if args.mcr_source is not None:
                        writer_result = bridge.request(
                            "POST",
                            "/api/v1/singleplayer",
                            {"action": "write_replay"},
                        )
                        replay_record = archive_combat_replay(
                            args.mcr_source,
                            replay_dir,
                            combat_index,
                            combat_started_wall,
                        )
                        replay_record["writer_result"] = writer_result
                        replay_archives.append(replay_record)
                    combat_index += 1
                    combat_started_wall = None

            episode_final_hp = state.get("player", {}).get("hp")
            episode_final_state_type = state.get("state_type")
            terminal = episode_final_state_type == "game_over"
            if terminal:
                player_dead = (
                    isinstance(episode_final_hp, (int, float))
                    and episode_final_hp <= 0
                )
                outcome = "loss" if player_dead else "win"
                grade: int | None = 0 if outcome == "loss" else 1
            else:
                outcome = "incomplete"
                grade = None

            reset_latencies: list[float] = []
            reset_exact_matches: list[bool] = []
            for reset_index in range(args.warm_resets):
                reset_started = time.monotonic()
                reset_result = bridge.request(
                    "POST",
                    "/api/v1/singleplayer",
                    {"action": "reset", "seed": args.seed},
                )
                reset_id = reset_result.get("reset_id")
                if not isinstance(reset_id, int):
                    raise RuntimeError(f"Reset was not accepted: {reset_result}")
                reset_deadline = time.monotonic() + args.startup_timeout
                while True:
                    reset_status = bridge.request(
                        "POST",
                        "/api/v1/singleplayer",
                        {"action": "reset_status"},
                    )
                    if reset_status.get("completed_reset_id", 0) >= reset_id:
                        if reset_status.get("error"):
                            raise RuntimeError(
                                f"Warm reset {reset_index} failed: "
                                f"{reset_status['error']}"
                            )
                        break
                    if time.monotonic() >= reset_deadline:
                        raise RuntimeError(
                            f"Warm reset {reset_index} did not reach combat within "
                            f"{args.startup_timeout:g} seconds"
                        )
                    time.sleep(0.005)
                state = bridge.request("GET", "/api/v1/singleplayer")
                if (
                    state.get("state_type") not in {"monster", "elite", "boss"}
                    or not state.get("battle", {}).get("is_play_phase")
                ):
                    raise RuntimeError(
                        f"Warm reset {reset_index} completed outside combat: "
                        f"{state.get('state_type')}"
                    )
                reset_latencies.append(time.monotonic() - reset_started)
                reset_exact_matches.append(state == initial_state)

            elapsed = time.monotonic() - started
            summary = {
                "actions": actions,
                "elapsed_seconds": elapsed,
                "actions_per_second_including_startup": actions / elapsed if elapsed else 0,
                "mean_action_to_state_change_ms": (
                    1000 * sum(latencies) / len(latencies) if latencies else None
                ),
                "initial_hp": initial_hp,
                "final_hp": episode_final_hp,
                "final_state_type": episode_final_state_type,
                "outcome": outcome,
                "grade": grade,
                "warm_resets": args.warm_resets,
                "warm_reset_mean_ms": (
                    1000 * sum(reset_latencies) / len(reset_latencies)
                    if reset_latencies
                    else None
                ),
                "warm_reset_latencies_ms": [
                    1000 * latency for latency in reset_latencies
                ],
                "warm_reset_exact_matches": reset_exact_matches,
                "combat_replays": replay_archives,
                "episode_dir": str(episode_dir),
                "initial_state": str(episode_dir / "initial.state"),
                "actions_file": str(episode_dir / "actions.jsonl"),
                "results_file": str(episode_dir / "results.jsonl"),
                "game_log": str(game_log_path),
            }
            game_log.flush()
            game_data_dir = args.game.parent / "data_sts2_windows_x86_64"
            mods_dir = args.game.parent / "mods"
            manifest = {
                "schema_version": 1,
                "episode_id": episode_dir.name,
                "mode": "full_run" if args.full_run else "combat",
                "started_at_utc": started_at_utc,
                "ended_at_utc": datetime.now(timezone.utc).isoformat(),
                "seed": args.seed,
                "policy_seed": args.policy_seed,
                "max_actions": args.max_actions,
                "launch": {
                    "game": str(args.game),
                    "args": command[1:],
                    "port": args.port,
                },
                "versions": game_version_metadata(game_log_path),
                "sha256": {
                    "sts2.dll": sha256_file(game_data_dir / "sts2.dll"),
                    "STS2_MCP.dll": sha256_file(
                        mods_dir / "STS2_MCP" / "STS2_MCP.dll"
                    ),
                    "STS2Bootstrap.dll": sha256_file(
                        mods_dir / "STS2_BOOTSTRAP" / "STS2_BOOTSTRAP.dll"
                    ),
                },
                "artifacts": {
                    "initial_state": "initial.state",
                    "actions": "actions.jsonl",
                    "results": "results.jsonl",
                    "game_log": "game.log",
                    "combat_replays": replay_archives,
                },
                "grade": {
                    "value": grade,
                    "outcome": outcome,
                    "terminal": terminal,
                    "scale": {
                        "loss": 0,
                        "win": 1,
                        "incomplete": None,
                    },
                },
                "summary": summary,
            }
            (episode_dir / "manifest.json").write_text(
                json.dumps(manifest, indent=2) + "\n",
                encoding="utf-8",
            )
            print(json.dumps(summary, indent=2))
            return 0
    finally:
        bridge.close()
        if pid_path.exists():
            windows_pid = pid_path.read_text(encoding="utf-8").strip()
            if windows_pid.isdecimal():
                subprocess.run(
                    [
                        "powershell.exe",
                        "-NoProfile",
                        "-Command",
                        f"Stop-Process -Id {windows_pid} -Force -ErrorAction SilentlyContinue",
                    ],
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        game_log.close()
        pid_path.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
