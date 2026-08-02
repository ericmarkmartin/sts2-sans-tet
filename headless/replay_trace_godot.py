#!/usr/bin/env python3
"""Replay a standalone episode semantically in Godot and report first parity divergence."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from benchmark_headless_episode import (
    Bridge,
    DEFAULT_GAME,
    powershell_literal,
    state_signature,
)
from headless.cross_backend_parity import (
    automatic_reconciliation_action,
    godot_phase,
    load_standalone_trace,
    normalize_godot,
    normalize_standalone,
    parity_diff,
    standalone_phase,
    translate_standalone_action,
)
def _jsonl(file: Any, value: dict[str, Any]) -> None:
    file.write(json.dumps(value, separators=(",", ":")) + "\n")
    file.flush()


def _allocate(root: Path, explicit: Path | None) -> Path:
    if explicit is not None:
        explicit.mkdir(parents=True, exist_ok=True)
        if any(explicit.iterdir()):
            raise RuntimeError(f"Parity directory is not empty: {explicit}")
        return explicit
    root.mkdir(parents=True, exist_ok=True)
    for index in range(1, 1_000_000):
        candidate = root / f"parity-{index:04d}"
        try:
            candidate.mkdir()
            return candidate
        except FileExistsError:
            continue
    raise RuntimeError(f"Could not allocate parity directory under {root}")


def _write_report(path: Path, report: dict[str, Any]) -> None:
    path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


def _is_actionable(source: dict[str, Any], godot: dict[str, Any]) -> bool:
    if standalone_phase(source) != godot_phase(godot):
        return False
    if standalone_phase(source) == "combat":
        return bool(godot.get("battle", {}).get("is_play_phase"))
    return True


def portable_profile_from_manifest(
    manifest: dict[str, Any],
) -> dict[str, Any]:
    profile = manifest.get("profile")
    if not isinstance(profile, dict):
        raise ValueError("Source episode manifest has no profile object")
    mode = profile.get("mode")
    if mode == "all_unlocks":
        return {"mode": "all_unlocks"}
    if mode != "progress_snapshot":
        raise ValueError(f"Unsupported source episode profile mode: {mode!r}")

    epochs = profile.get("unlocked_epoch_ids")
    encounters = profile.get("encounter_ids_seen")
    number_of_runs = profile.get("number_of_runs")
    if not isinstance(epochs, list) or not all(
        isinstance(value, str) for value in epochs
    ):
        raise ValueError("Profile unlocked_epoch_ids must be a list of strings")
    if not isinstance(encounters, list) or not all(
        isinstance(value, str) for value in encounters
    ):
        raise ValueError("Profile encounter_ids_seen must be a list of strings")
    if type(number_of_runs) is not int or number_of_runs < 0:
        raise ValueError("Profile number_of_runs must be a nonnegative integer")

    snapshot = {
        "unlocked_epoch_ids": epochs,
        "encounter_ids_seen": encounters,
        "number_of_runs": number_of_runs,
    }
    canonical = json.dumps(
        snapshot, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    actual_sha256 = hashlib.sha256(canonical).hexdigest()
    recorded_sha256 = profile.get("sha256")
    if recorded_sha256 != actual_sha256:
        raise ValueError(
            "Source episode profile snapshot checksum does not match its "
            f"contents (recorded={recorded_sha256}, actual={actual_sha256})"
        )
    return {
        "mode": "progress_snapshot",
        **snapshot,
        "sha256": actual_sha256,
    }


def episode_character(
    manifest: dict[str, Any], initial_state: dict[str, Any]
) -> str:
    character = manifest.get("character")
    supported = {"Ironclad", "Silent", "Defect", "Regent", "Necrobinder"}
    if character in supported:
        return character

    player_name = initial_state.get("player", {}).get("name")
    inferred = {
        "The Ironclad": "Ironclad",
        "The Silent": "Silent",
        "The Defect": "Defect",
        "The Regent": "Regent",
        "The Necrobinder": "Necrobinder",
    }.get(player_name)
    if inferred is not None:
        return inferred
    raise ValueError(
        f"Source episode has no supported character metadata: {character!r}"
    )


def episode_ascension(manifest: dict[str, Any]) -> int:
    ascension = manifest.get("ascension", 0)
    if ascension is None and manifest.get("schema_version") == 1:
        return 0
    if type(ascension) is not int or ascension < 0:
        raise ValueError(
            f"Source episode has invalid ascension metadata: {ascension!r}"
        )
    return ascension


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_episode", type=Path)
    parser.add_argument("--game", type=Path, default=DEFAULT_GAME)
    parser.add_argument("--port", type=int, default=15526)
    parser.add_argument("--startup-timeout", type=float, default=60)
    parser.add_argument("--settle-timeout", type=float, default=5)
    parser.add_argument(
        "--movie",
        type=Path,
        help="capture this replay to a Godot Movie Maker AVI",
    )
    parser.add_argument("--fixed-fps", type=int, default=30)
    parser.add_argument("--resolution", default="1280x720")
    parser.add_argument("--frame-delay-ms", type=int, default=34)
    parser.add_argument("--action-delay", type=float, default=0.35)
    parser.add_argument("--render-tail-frames", type=int, default=30)
    parser.add_argument(
        "--game-speed",
        choices=("instant", "fast", "normal"),
        default="instant",
    )
    parser.add_argument(
        "--parity-runs-dir", type=Path, default=Path("headless/parity-runs")
    )
    parser.add_argument("--parity-dir", type=Path)
    args = parser.parse_args()

    if args.fixed_fps <= 0:
        raise ValueError("--fixed-fps must be positive")
    if args.frame_delay_ms < 0:
        raise ValueError("--frame-delay-ms must be nonnegative")
    if args.action_delay < 0:
        raise ValueError("--action-delay must be nonnegative")
    if not 0 <= args.render_tail_frames <= 600:
        raise ValueError("--render-tail-frames must be between 0 and 600")
    resolution_parts = args.resolution.lower().split("x", maxsplit=1)
    if (
        len(resolution_parts) != 2
        or not all(part.isdecimal() and int(part) > 0 for part in resolution_parts)
    ):
        raise ValueError("--resolution must look like 1280x720")

    source_episode = args.source_episode.resolve()
    source_initial, steps, source_manifest = load_standalone_trace(source_episode)
    seed = str(source_manifest.get("seed") or "")
    if not seed:
        raise RuntimeError("Source episode manifest has no seed")
    source_profile = portable_profile_from_manifest(source_manifest)
    character = episode_character(source_manifest, source_initial)
    ascension = episode_ascension(source_manifest)
    parity_dir = _allocate(args.parity_runs_dir, args.parity_dir)
    movie_path: Path | None = None
    if args.movie is not None:
        movie_path = args.movie.resolve()
        movie_path.parent.mkdir(parents=True, exist_ok=True)
        if movie_path.exists():
            raise RuntimeError(f"Movie output already exists: {movie_path}")
    profile_snapshot_path = (parity_dir / "profile-snapshot.json").resolve()
    profile_snapshot_path.write_text(
        json.dumps(source_profile, indent=2) + "\n", encoding="utf-8"
    )
    report_path = parity_dir / "parity.json"
    game_log_path = parity_dir / "game.log"
    report: dict[str, Any] = {
        "schema_version": 1,
        "source_episode": str(source_episode),
        "source_episode_id": source_manifest.get("episode_id"),
        "seed": seed,
        "character": character,
        "ascension": ascension,
        "profile_mode": source_profile["mode"],
        "profile_sha256": source_profile.get("sha256"),
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "running",
        "source_actions": len(steps),
        "source_actions_consumed": 0,
        "godot_actions": 0,
        "automatic_actions": 0,
        "checkpoints": [],
        "divergence": None,
        "render": (
            {
                "movie": str(movie_path),
                "fixed_fps": args.fixed_fps,
                "resolution": args.resolution,
                "frame_delay_ms": args.frame_delay_ms,
                "action_delay_seconds": args.action_delay,
                "tail_frames": args.render_tail_frames,
                "game_speed": args.game_speed,
                "muted": True,
                "finish_result": None,
            }
            if movie_path is not None
            else None
        ),
    }
    _write_report(report_path, report)

    with socket.socket() as probe:
        probe.settimeout(0.2)
        if probe.connect_ex(("127.0.0.1", args.port)) == 0:
            raise RuntimeError(
                f"Port {args.port} is already accepting connections"
            )

    pid_path = (parity_dir / ".game.pid").resolve()
    windows_game_path = subprocess.check_output(
        ["wslpath", "-w", str(args.game)], text=True
    ).strip()
    windows_pid_path = subprocess.check_output(
        ["wslpath", "-w", str(pid_path)], text=True
    ).strip()
    windows_profile_snapshot_path = subprocess.check_output(
        ["wslpath", "-w", str(profile_snapshot_path)], text=True
    ).strip()
    if movie_path is None:
        game_args = ["--headless", "--audio-driver", "Dummy", "--bootstrap"]
    else:
        windows_movie_path = subprocess.check_output(
            ["wslpath", "-w", str(movie_path)], text=True
        ).strip()
        game_args = [
            "--bootstrap",
            "--audio-driver",
            "Dummy",
            "--write-movie",
            windows_movie_path,
            "--fixed-fps",
            str(args.fixed_fps),
            "--frame-delay",
            str(args.frame_delay_ms),
            "--resolution",
            args.resolution,
            "--windowed",
            "--disable-vsync",
        ]
    launch_parts = [
        f"$env:STS2_BOOTSTRAP_SEED={powershell_literal(seed)}; ",
        "$env:STS2_BOOTSTRAP_MODE='full'; ",
        f"$env:STS2_BOOTSTRAP_CHARACTER={powershell_literal(character)}; ",
        f"$env:STS2_BOOTSTRAP_ASCENSION={powershell_literal(str(ascension))}; ",
        f"$env:STS2_BOOTSTRAP_FAST_MODE={powershell_literal(args.game_speed)}; ",
        "$env:STS2_BOOTSTRAP_PROFILE_SNAPSHOT=",
        f"{powershell_literal(windows_profile_snapshot_path)}; ",
    ]
    if movie_path is not None:
        launch_parts.append(
            "$env:STS2_BOOTSTRAP_RENDER='1'; "
            "$env:STS2_BOOTSTRAP_RENDER_TAIL_FRAMES="
            f"{powershell_literal(str(args.render_tail_frames))}; "
        )
    launch_parts.extend(
        [
            f"$p=Start-Process -FilePath {powershell_literal(windows_game_path)} "
            f"-ArgumentList @({','.join(powershell_literal(arg) for arg in game_args)}) ",
            "-NoNewWindow -PassThru; "
            f"[IO.File]::WriteAllText({powershell_literal(windows_pid_path)},[string]$p.Id); ",
            "$p.WaitForExit(); exit $p.ExitCode",
        ]
    )
    launch_script = "".join(launch_parts)
    game_log = game_log_path.open("wb")
    process = subprocess.Popen(
        ["powershell.exe", "-NoProfile", "-Command", launch_script],
        cwd=args.game.parent,
        env=os.environ.copy(),
        stdout=game_log,
        stderr=subprocess.STDOUT,
    )
    bridge = Bridge(args.port)
    started = time.monotonic()
    actions_file = (parity_dir / "actions.jsonl").open("w", encoding="utf-8")
    states_file = (parity_dir / "states.jsonl").open("w", encoding="utf-8")
    try:
        deadline = time.monotonic() + args.startup_timeout
        state: dict[str, Any] | None = None
        while time.monotonic() < deadline and process.poll() is None:
            try:
                candidate = bridge.request("GET", "/api/v1/singleplayer")
                if candidate.get("state_type") not in {
                    None,
                    "unknown",
                    "menu",
                }:
                    state = candidate
                    break
            except (OSError, RuntimeError, json.JSONDecodeError):
                bridge.close()
                bridge = Bridge(args.port)
            time.sleep(0.01)
        if state is None:
            raise RuntimeError("Godot reference run did not become ready")

        cursor = 0
        mismatch_deadline = time.monotonic() + args.settle_timeout
        last_signature = state_signature(state)
        while True:
            expected = steps[cursor]["before"] if cursor < len(steps) else steps[-1]["after"]
            differences = parity_diff(expected, state)
            if not differences and _is_actionable(expected, state):
                checkpoint = {
                    "source_action_index": (
                        steps[cursor]["source_index"]
                        if cursor < len(steps)
                        else None
                    ),
                    "phase": standalone_phase(expected),
                    "standalone": normalize_standalone(expected),
                    "godot": normalize_godot(state),
                }
                report["checkpoints"].append(checkpoint)
                _write_report(report_path, report)
                if cursor >= len(steps):
                    report["status"] = "matched"
                    break
                step = steps[cursor]
                action = translate_standalone_action(
                    step["before"], step["action"], state
                )
                source_index: int | None = step["source_index"]
                automatic = False
            else:
                action = automatic_reconciliation_action(expected, state)
                source_index = None
                automatic = action is not None
                if action is None:
                    time.sleep(0.01)
                    candidate = bridge.request("GET", "/api/v1/singleplayer")
                    signature = state_signature(candidate)
                    if signature != last_signature:
                        state = candidate
                        last_signature = signature
                        mismatch_deadline = time.monotonic() + args.settle_timeout
                        _jsonl(
                            states_file,
                            {
                                "kind": "async_state",
                                "t": time.monotonic() - started,
                                "state": state,
                            },
                        )
                        continue
                    if time.monotonic() < mismatch_deadline:
                        continue
                    report["status"] = "diverged"
                    report["divergence"] = {
                        "source_action_index": (
                            steps[cursor]["source_index"]
                            if cursor < len(steps)
                            else None
                        ),
                        "standalone_phase": standalone_phase(expected),
                        "godot_phase": godot_phase(state),
                        "differences": differences,
                        "standalone": normalize_standalone(expected),
                        "godot": normalize_godot(state),
                    }
                    break

            before = state_signature(state)
            action_index = report["godot_actions"]
            _jsonl(
                actions_file,
                {
                    "index": action_index,
                    "t": time.monotonic() - started,
                    "source_action_index": source_index,
                    "automatic": automatic,
                    "action": action,
                },
            )
            if movie_path is not None and args.action_delay:
                time.sleep(args.action_delay)
            result = bridge.request("POST", "/api/v1/singleplayer", action)
            report["godot_actions"] += 1
            if automatic:
                report["automatic_actions"] += 1
            if result.get("status") not in {"ok", "accepted"}:
                report["status"] = "error"
                report["divergence"] = {
                    "source_action_index": source_index,
                    "action": action,
                    "result": result,
                }
                break
            if source_index is not None:
                cursor += 1
                report["source_actions_consumed"] = cursor
            change_deadline = time.monotonic() + 10
            while True:
                candidate = bridge.request("GET", "/api/v1/singleplayer")
                if state_signature(candidate) != before:
                    state = candidate
                    last_signature = state_signature(state)
                    break
                if time.monotonic() >= change_deadline:
                    raise RuntimeError(f"State did not change after {action}")
                time.sleep(0.005)
            mismatch_deadline = time.monotonic() + args.settle_timeout
            _jsonl(
                states_file,
                {
                    "kind": "action_result",
                    "index": action_index,
                    "source_action_index": source_index,
                    "automatic": automatic,
                    "t": time.monotonic() - started,
                    "result": result,
                    "state": state,
                },
            )

        if movie_path is not None:
            finish_result = bridge.request(
                "POST", "/api/v1/singleplayer", {"action": "finish_render"}
            )
            report["render"]["finish_result"] = finish_result
            if finish_result.get("status") != "accepted":
                raise RuntimeError(
                    f"Bootstrap rejected finish_render: {finish_result}"
                )
            process.wait(timeout=30)
            if process.returncode not in {None, 0}:
                raise RuntimeError(
                    f"Rendered game exited with code {process.returncode}"
                )
            if not movie_path.is_file() or movie_path.stat().st_size == 0:
                raise RuntimeError(f"Godot did not produce a movie: {movie_path}")

        report["ended_at_utc"] = datetime.now(timezone.utc).isoformat()
        report["elapsed_seconds"] = time.monotonic() - started
        _write_report(report_path, report)
        print(
            json.dumps(
                {
                    "status": report["status"],
                    "source_episode_id": report["source_episode_id"],
                    "source_actions": report["source_actions"],
                    "source_actions_consumed": report[
                        "source_actions_consumed"
                    ],
                    "godot_actions": report["godot_actions"],
                    "automatic_actions": report["automatic_actions"],
                    "elapsed_seconds": report["elapsed_seconds"],
                    "parity_report": str(report_path),
                    "divergence": report["divergence"],
                },
                indent=2,
            )
        )
        return 0 if report["status"] == "matched" else 1
    finally:
        actions_file.close()
        states_file.close()
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
