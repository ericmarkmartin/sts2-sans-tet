#!/usr/bin/env python3
"""Replay a standalone episode semantically in Godot and report first parity divergence."""

from __future__ import annotations

import argparse
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
from headless.sts2_cli_episode import load_progress_snapshot


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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_episode", type=Path)
    parser.add_argument("--game", type=Path, default=DEFAULT_GAME)
    parser.add_argument("--port", type=int, default=15526)
    parser.add_argument("--startup-timeout", type=float, default=60)
    parser.add_argument("--settle-timeout", type=float, default=5)
    parser.add_argument(
        "--progress-save",
        type=Path,
        help="active Godot progress.save; required for profile-backed episodes",
    )
    parser.add_argument(
        "--parity-runs-dir", type=Path, default=Path("headless/parity-runs")
    )
    parser.add_argument("--parity-dir", type=Path)
    args = parser.parse_args()

    source_episode = args.source_episode.resolve()
    source_initial, steps, source_manifest = load_standalone_trace(source_episode)
    seed = str(source_manifest.get("seed") or "")
    if not seed:
        raise RuntimeError("Source episode manifest has no seed")
    source_profile = source_manifest.get("profile", {})
    if source_profile.get("mode") == "progress_snapshot":
        if args.progress_save is None:
            raise RuntimeError(
                "Profile-backed episode requires --progress-save so the "
                "active Godot profile can be verified"
            )
        active_profile = load_progress_snapshot(args.progress_save.resolve())
        if active_profile["sha256"] != source_profile.get("sha256"):
            raise RuntimeError(
                "Godot profile snapshot does not match the source episode "
                f"(source={source_profile.get('sha256')}, "
                f"active={active_profile['sha256']})"
            )
    parity_dir = _allocate(args.parity_runs_dir, args.parity_dir)
    report_path = parity_dir / "parity.json"
    game_log_path = parity_dir / "game.log"
    report: dict[str, Any] = {
        "schema_version": 1,
        "source_episode": str(source_episode),
        "source_episode_id": source_manifest.get("episode_id"),
        "seed": seed,
        "profile_sha256": source_profile.get("sha256"),
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "running",
        "source_actions": len(steps),
        "source_actions_consumed": 0,
        "godot_actions": 0,
        "automatic_actions": 0,
        "checkpoints": [],
        "divergence": None,
    }
    _write_report(report_path, report)

    with socket.socket() as probe:
        probe.settimeout(0.2)
        if probe.connect_ex(("127.0.0.1", args.port)) == 0:
            raise RuntimeError(
                f"Port {args.port} is already accepting connections"
            )

    game_args = ["--headless", "--audio-driver", "Dummy", "--bootstrap"]
    pid_path = (parity_dir / ".game.pid").resolve()
    windows_game_path = subprocess.check_output(
        ["wslpath", "-w", str(args.game)], text=True
    ).strip()
    windows_pid_path = subprocess.check_output(
        ["wslpath", "-w", str(pid_path)], text=True
    ).strip()
    launch_script = (
        f"$env:STS2_BOOTSTRAP_SEED={powershell_literal(seed)}; "
        "$env:STS2_BOOTSTRAP_MODE='full'; "
        f"$p=Start-Process -FilePath {powershell_literal(windows_game_path)} "
        f"-ArgumentList @({','.join(powershell_literal(arg) for arg in game_args)}) "
        "-NoNewWindow -PassThru; "
        f"[IO.File]::WriteAllText({powershell_literal(windows_pid_path)},[string]$p.Id); "
        "$p.WaitForExit(); exit $p.ExitCode"
    )
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
