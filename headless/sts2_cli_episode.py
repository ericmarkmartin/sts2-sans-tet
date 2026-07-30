#!/usr/bin/env python3
"""Record one full sts2-cli run in the repository's episode format."""

from __future__ import annotations

import argparse
import json
import os
import random
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from benchmark_headless_episode import allocate_episode_dir, sha256_file
from headless.validate_episode import validate_episode


class Sts2Cli:
    """One request/one response NDJSON client for the standalone simulator."""

    def __init__(
        self,
        dotnet: str,
        dll: Path,
        game_log: Any,
        *,
        cli_lib: Path | None = None,
        game_data_dir: Path | None = None,
    ) -> None:
        environment = os.environ.copy()
        if cli_lib is not None:
            environment["STS2_LIB"] = str(cli_lib.resolve())
        if game_data_dir is not None:
            environment["STS2_GAME_DIR"] = str(game_data_dir.resolve())
        self.process = subprocess.Popen(
            [dotnet, str(dll.resolve())],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=game_log,
            text=True,
            bufsize=1,
            env=environment,
        )
        try:
            self.ready = self._read()
            if self.ready.get("type") != "ready":
                raise RuntimeError(
                    f"Expected sts2-cli ready message, got {self.ready}"
                )
        except Exception:
            if self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=5)
            raise

    def _read(self) -> dict[str, Any]:
        assert self.process.stdout is not None
        while True:
            line = self.process.stdout.readline()
            if not line:
                code = self.process.poll()
                raise RuntimeError(f"sts2-cli closed stdout (exit code {code})")
            line = line.strip()
            if not line.startswith("{"):
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise RuntimeError(f"sts2-cli returned non-object JSON: {value!r}")
            return value

    def send(self, command: dict[str, Any]) -> dict[str, Any]:
        if self.process.poll() is not None:
            raise RuntimeError(f"sts2-cli exited with code {self.process.returncode}")
        assert self.process.stdin is not None
        self.process.stdin.write(
            json.dumps(command, separators=(",", ":")) + "\n"
        )
        self.process.stdin.flush()
        return self._read()

    def close(self) -> None:
        if self.process.poll() is None:
            try:
                self.send({"cmd": "quit"})
            except (BrokenPipeError, RuntimeError, json.JSONDecodeError):
                pass
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)


def _action(name: str, **arguments: Any) -> dict[str, Any]:
    command: dict[str, Any] = {"cmd": "action", "action": name}
    if arguments:
        command["args"] = arguments
    return command


def choose_sts2_cli_action(
    state: dict[str, Any], rng: random.Random
) -> dict[str, Any] | None:
    """Choose a legal baseline action from an sts2-cli decision response."""
    decision = state.get("decision")
    if decision == "game_over":
        return None
    if decision == "map_select":
        choices = state.get("choices", [])
        if not choices:
            return _action("proceed")
        choice = rng.choice(choices)
        return _action("select_map_node", col=choice["col"], row=choice["row"])
    if decision == "combat_play":
        energy = int(state.get("energy") or 0)
        playable = [
            card
            for card in state.get("hand", [])
            if card.get("can_play") and int(card.get("cost") or 0) <= energy
        ]
        if not playable:
            return _action("end_turn")
        card = playable[0]
        arguments = {"card_index": card["index"]}
        if card.get("target_type") == "AnyEnemy":
            enemies = state.get("enemies", [])
            if not enemies:
                return _action("end_turn")
            arguments["target_index"] = enemies[0]["index"]
        return _action("play_card", **arguments)
    if decision in {"event_choice", "rest_site"}:
        options = state.get("options", [])
        enabled = [
            option
            for option in options
            if not option.get("is_locked") and option.get("is_enabled", True)
        ]
        if not enabled:
            return _action("leave_room")
        if decision == "rest_site":
            heal = next(
                (option for option in enabled if option.get("option_id") == "HEAL"),
                None,
            )
            choice = heal or enabled[0]
        else:
            choice = enabled[0]
        return _action("choose_option", option_index=choice["index"])
    if decision == "card_reward":
        cards = state.get("cards", [])
        if cards:
            return _action("select_card_reward", card_index=0)
        return _action("skip_card_reward")
    if decision == "bundle_select":
        return _action("select_bundle", bundle_index=0)
    if decision == "card_select":
        cards = state.get("cards", [])
        minimum = int(state.get("min_select") or 0)
        if cards and minimum:
            indexes = ",".join(str(index) for index in range(min(minimum, len(cards))))
            return _action("select_cards", indices=indexes)
        return _action("skip_select")
    if decision == "shop":
        return _action("leave_room")
    return _action("proceed")


def _jsonl(file: Any, value: dict[str, Any]) -> None:
    file.write(json.dumps(value, separators=(",", ":")) + "\n")
    file.flush()


def _git_revision(path: Path) -> str | None:
    result = subprocess.run(
        ["git", "-C", str(path), "rev-parse", "HEAD"],
        text=True,
        capture_output=True,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def _find_cli_root(dll: Path) -> Path | None:
    for candidate in [dll.parent, *dll.parents]:
        if (candidate / ".git").exists() and (candidate / "src/Sts2Headless").exists():
            return candidate
    return None


def run_episode(args: argparse.Namespace) -> Path:
    dll = args.cli_dll.resolve()
    if not dll.is_file():
        raise FileNotFoundError(f"sts2-cli DLL does not exist: {dll}")
    cli_root = _find_cli_root(dll)
    cli_lib = args.cli_lib.resolve() if args.cli_lib else None
    if cli_lib is None and cli_root is not None and (cli_root / "lib").is_dir():
        cli_lib = cli_root / "lib"

    episode_dir = allocate_episode_dir(args.episodes_dir, args.episode_dir)
    game_log_path = episode_dir / "game.log"
    started = time.monotonic()
    started_at = datetime.now(timezone.utc).isoformat()
    rng = random.Random(args.policy_seed)
    actions = 0
    state: dict[str, Any] | None = None
    ready: dict[str, Any] | None = None
    failure: str | None = None
    client: Sts2Cli | None = None

    with (
        game_log_path.open("w", encoding="utf-8") as game_log,
        (episode_dir / "actions.jsonl").open("w", encoding="utf-8") as actions_file,
        (episode_dir / "results.jsonl").open("w", encoding="utf-8") as results_file,
    ):
        try:
            client = Sts2Cli(
                args.dotnet,
                dll,
                game_log,
                cli_lib=cli_lib,
                game_data_dir=args.game_data_dir,
            )
            ready = client.ready
            state = client.send(
                {
                    "cmd": "start_run",
                    "character": args.character,
                    "ascension": args.ascension,
                    "seed": args.seed,
                    "lang": args.lang,
                    "observation_mode": args.observation_mode,
                }
            )
            if state.get("type") == "error":
                raise RuntimeError(state.get("message", "start_run failed"))
            (episode_dir / "initial.state").write_text(
                json.dumps(state, indent=2) + "\n", encoding="utf-8"
            )

            while actions < args.max_actions:
                command = choose_sts2_cli_action(state, rng)
                if command is None:
                    break
                action_index = actions
                action_started = time.monotonic()
                _jsonl(
                    actions_file,
                    {
                        "index": action_index,
                        "t": action_started - started,
                        "action": command,
                    },
                )
                next_state = client.send(command)
                actions += 1
                _jsonl(
                    results_file,
                    {
                        "kind": "action_result",
                        "index": action_index,
                        "t": time.monotonic() - started,
                        "result": {
                            "status": (
                                "error" if next_state.get("type") == "error" else "ok"
                            )
                        },
                        "state": next_state,
                    },
                )
                if next_state.get("type") == "error":
                    raise RuntimeError(
                        f"Action {action_index} failed: "
                        f"{next_state.get('message', next_state)}"
                    )
                state = next_state
        except Exception as exception:
            failure = f"{type(exception).__name__}: {exception}"
            game_log.write(f"[episode-runner] {failure}\n")
            game_log.flush()
        finally:
            if client is not None:
                client.close()

    if not (episode_dir / "initial.state").exists():
        (episode_dir / "initial.state").write_text(
            json.dumps(state or {"type": "error", "message": failure}, indent=2)
            + "\n",
            encoding="utf-8",
        )

    final_decision = state.get("decision") if state else None
    terminal = final_decision == "game_over"
    victory = bool(state.get("victory")) if terminal and state else False
    outcome = "win" if victory else "loss" if terminal else "incomplete"
    grade = 1 if outcome == "win" else 0 if outcome == "loss" else None
    elapsed = time.monotonic() - started
    summary = {
        "actions": actions,
        "elapsed_seconds": elapsed,
        "actions_per_second_including_startup": actions / elapsed if elapsed else 0,
        "final_state_type": "game_over" if terminal else final_decision,
        "outcome": outcome,
        "grade": grade,
        "act": state.get("act") if state else None,
        "floor": state.get("floor") if state else None,
        "final_hp": (state or {}).get("player", {}).get("hp"),
        "failure": failure,
        "episode_dir": str(episode_dir),
    }
    original_dll = cli_lib / "sts2.dll.original" if cli_lib else None
    patched_dll = cli_lib / "sts2.dll" if cli_lib else None
    manifest = {
        "schema_version": 1,
        "episode_id": episode_dir.name,
        "mode": "full_run",
        "backend": "sts2-cli",
        "started_at_utc": started_at,
        "ended_at_utc": datetime.now(timezone.utc).isoformat(),
        "seed": args.seed,
        "policy_seed": args.policy_seed,
        "max_actions": args.max_actions,
        "observation": {
            "schema": "sts2-cli.observation.v1",
            "mode": args.observation_mode,
        },
        "launch": {
            "dotnet": args.dotnet,
            "dll": str(dll),
            "cli_lib": str(cli_lib) if cli_lib else None,
            "game_data_dir": (
                str(args.game_data_dir.resolve()) if args.game_data_dir else None
            ),
        },
        "versions": {
            "protocol": ready.get("version") if ready else None,
            "sts2_cli_git": _git_revision(cli_root) if cli_root else None,
        },
        "sha256": {
            "sts2_cli.dll": sha256_file(dll),
            "sts2.dll": sha256_file(original_dll) if original_dll else None,
            "sts2.patched.dll": sha256_file(patched_dll) if patched_dll else None,
        },
        "artifacts": {
            "initial_state": "initial.state",
            "actions": "actions.jsonl",
            "results": "results.jsonl",
            "game_log": "game.log",
            "combat_replays": [],
        },
        "grade": {
            "value": grade,
            "outcome": outcome,
            "terminal": terminal,
            "scale": {"loss": 0, "win": 1, "incomplete": None},
        },
        "summary": summary,
    }
    (episode_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    validation = validate_episode(episode_dir)
    if not validation.valid:
        details = "; ".join(validation.errors)
        raise RuntimeError(
            f"episode validation failed at {episode_dir}: {details}"
        )
    output_summary = {
        **summary,
        "validation": {
            "valid": True,
            "warnings": validation.warnings,
        },
    }
    print(json.dumps(output_summary, indent=2))
    if failure is not None:
        raise RuntimeError(f"{failure}; partial episode preserved at {episode_dir}")
    return episode_dir


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--cli-dll",
        type=Path,
        default=os.environ.get("STS2_CLI_DLL"),
        required=os.environ.get("STS2_CLI_DLL") is None,
        help="built Sts2Headless.dll (or set STS2_CLI_DLL)",
    )
    parser.add_argument(
        "--cli-lib",
        type=Path,
        help="sts2-cli lib directory; auto-detected from a source checkout",
    )
    parser.add_argument("--game-data-dir", type=Path)
    parser.add_argument("--dotnet", default="dotnet")
    parser.add_argument("--character", default="Ironclad")
    parser.add_argument("--ascension", type=int, default=0)
    parser.add_argument("--seed", default="HEADLESSBENCH")
    parser.add_argument("--policy-seed", type=int, default=0)
    parser.add_argument("--lang", default="en")
    parser.add_argument(
        "--observation-mode",
        choices=("human", "authoritative"),
        default="human",
    )
    parser.add_argument("--max-actions", type=int, default=5000)
    parser.add_argument("--episodes-dir", type=Path, default=Path("headless/episodes"))
    parser.add_argument("--episode-dir", type=Path)
    return parser.parse_args(argv)


def main() -> int:
    try:
        run_episode(parse_args())
    except Exception as exception:
        print(f"error: {exception}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
