#!/usr/bin/env python3
"""Verify the exact installed runtime used for full-episode rendering."""

from __future__ import annotations

import argparse
import json
import shutil
import socket
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from headless.validate_episode import sha256_file

DEFAULT_GAME_DIR = Path(
    "/mnt/c/Program Files (x86)/Steam/steamapps/common/Slay the Spire 2"
)
DEFAULT_LOCK = REPO_ROOT / "headless" / "render-runtime-lock.json"


def verify_render_environment(
    game_dir: Path,
    episode_dir: Path,
    *,
    lock_path: Path = DEFAULT_LOCK,
    port: int = 15526,
    require_commands: bool = True,
    require_free_port: bool = True,
) -> dict[str, Any]:
    game_dir = game_dir.resolve()
    episode_dir = episode_dir.resolve()
    errors: list[str] = []
    files: dict[str, dict[str, Any]] = {}

    try:
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exception:
        return {
            "valid": False,
            "errors": [f"cannot read runtime lock {lock_path}: {exception}"],
            "files": files,
        }
    if lock.get("schema_version") != 1 or not isinstance(lock.get("files"), dict):
        return {
            "valid": False,
            "errors": ["unsupported or malformed render runtime lock"],
            "files": files,
        }

    for relative, expected_hash in lock["files"].items():
        relative_path = Path(relative)
        if (
            relative_path.is_absolute()
            or ".." in relative_path.parts
            or not isinstance(expected_hash, str)
        ):
            errors.append(f"invalid runtime-lock entry: {relative!r}")
            continue
        path = game_dir / relative_path
        if not path.is_file():
            errors.append(f"missing installed runtime file: {relative}")
            continue
        actual_hash = sha256_file(path)
        files[relative] = {
            "path": str(path),
            "sha256": actual_hash,
            "size": path.stat().st_size,
        }
        if actual_hash != expected_hash:
            errors.append(
                f"runtime hash mismatch for {relative}: "
                f"expected {expected_hash}, found {actual_hash}"
            )

    manifest_path = episode_dir / "manifest.json"
    try:
        episode_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exception:
        errors.append(f"cannot read episode manifest: {exception}")
        episode_manifest = {}
    episode_game_hash = episode_manifest.get("sha256", {}).get("sts2.dll")
    installed_game = files.get("data_sts2_windows_x86_64/sts2.dll", {})
    if not isinstance(episode_game_hash, str):
        errors.append("episode manifest does not record the original sts2.dll hash")
    elif installed_game.get("sha256") != episode_game_hash:
        errors.append(
            "episode game DLL hash does not match the installed rendering build"
        )

    commands: dict[str, str] = {}
    if require_commands:
        for command in ("powershell.exe", "wslpath", "ffmpeg", "ffprobe"):
            resolved = shutil.which(command)
            if resolved is None:
                errors.append(f"required command is unavailable: {command}")
            else:
                commands[command] = resolved

    if require_free_port:
        with socket.socket() as probe:
            probe.settimeout(0.2)
            if probe.connect_ex(("127.0.0.1", port)) == 0:
                errors.append(f"render bridge port {port} is already in use")

    return {
        "valid": not errors,
        "errors": errors,
        "game_dir": str(game_dir),
        "episode_dir": str(episode_dir),
        "runtime_lock": {
            "path": str(lock_path.resolve()),
            "sha256": sha256_file(lock_path),
            "release": lock.get("release"),
        },
        "files": files,
        "commands": commands,
        "port": port,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("episode_dir", type=Path)
    parser.add_argument("--game-dir", type=Path, default=DEFAULT_GAME_DIR)
    parser.add_argument("--lock", type=Path, default=DEFAULT_LOCK)
    parser.add_argument("--port", type=int, default=15526)
    args = parser.parse_args()
    report = verify_render_environment(
        args.game_dir, args.episode_dir, lock_path=args.lock, port=args.port
    )
    print(json.dumps(report, indent=2))
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
