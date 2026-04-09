"""Game process launcher for STS2 with RL Bridge mod."""

from __future__ import annotations

import subprocess
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_GAME_PATH = Path(r"C:\Program Files (x86)\Steam\steamapps\common\Slay the Spire 2\SlayTheSpire2.exe")


def launch_game(
    game_path: Path | str = DEFAULT_GAME_PATH,
    seed: str | None = None,
    port: int = 19720,
    log_file: str | None = None,
) -> subprocess.Popen:
    """Launch STS2 with AutoSlay and RL Bridge mod.

    The game must have the rl_bridge mod installed in its mods/ directory.
    """
    game_path = Path(game_path)
    if not game_path.exists():
        raise FileNotFoundError(f"Game not found at {game_path}")

    args = [str(game_path), "--autoslay"]

    if seed:
        args.extend(["--seed", seed])

    if log_file:
        args.extend(["--log-file", log_file])

    env = {"RL_BRIDGE_PORT": str(port)}

    logger.info(f"Launching game: {' '.join(args)}")
    process = subprocess.Popen(
        args,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    logger.info(f"Game launched with PID {process.pid}")
    return process
