"""Gymnasium environment for Slay the Spire 2."""

from __future__ import annotations

import logging
from typing import Any

import gymnasium as gym
import numpy as np

from sts2_rl.connection import ConnectionServer
from sts2_rl.reward import compute_reward

logger = logging.getLogger(__name__)


class STS2Env(gym.Env):
    """Gymnasium-compatible environment for STS2 via the RL Bridge mod.

    The game runs separately with the rl_bridge mod loaded. This environment
    communicates with it via TCP to receive observations and send actions.

    Observations and actions are dict-based (not fixed-size arrays) since
    STS2 has variable-size hands, enemy counts, etc.
    """

    metadata = {"render_modes": []}

    def __init__(self, port: int = 19720, host: str = "127.0.0.1"):
        super().__init__()
        self.connection = ConnectionServer(port=port, host=host)
        self._prev_run_context: dict | None = None
        self._episode_count = 0

        # Variable action/obs spaces — we use Dict spaces as documentation
        # but the actual values are dicts, not numpy arrays
        self.observation_space = gym.spaces.Dict({})
        self.action_space = gym.spaces.Dict({})

    def reset(self, *, seed: int | None = None, options: dict | None = None) -> tuple[dict, dict]:
        """Wait for the game to send the first observation of a new episode."""
        if self._episode_count == 0:
            self.connection.start()
            self.connection.wait_for_connection()

        self._episode_count += 1
        logger.info(f"Episode {self._episode_count} starting, waiting for first obs...")

        # Wait for first observation from game
        msg = self.connection.receive()

        # If we got an episode_end from a previous run, ack and wait for real obs
        if msg.get("type") == "episode_end":
            self.connection.send({"type": "reset_ack"})
            msg = self.connection.receive()

        obs = self._parse_obs(msg)
        info = self._build_info(msg)
        self._prev_run_context = msg.get("run_context", {})

        return obs, info

    def step(self, action: dict) -> tuple[dict, float, bool, bool, dict]:
        """Send an action to the game and receive the next observation."""
        self.connection.send(self._encode_action(action))

        msg = self.connection.receive()

        if msg.get("type") == "episode_end":
            obs = self._parse_episode_end(msg)
            reward = compute_reward(msg, self._prev_run_context)
            info = {
                "result": msg.get("result", "unknown"),
                "floor_reached": msg.get("floor_reached", 0),
                "final_hp": msg.get("final_hp", 0),
                "episode_end": True,
            }
            self._prev_run_context = msg.get("run_context", {})

            # Send reset_ack so game starts next episode
            self.connection.send({"type": "reset_ack"})

            return obs, reward, True, False, info

        obs = self._parse_obs(msg)
        reward = compute_reward(msg, self._prev_run_context)
        info = self._build_info(msg)
        self._prev_run_context = msg.get("run_context", {})

        return obs, reward, False, False, info

    def close(self) -> None:
        self.connection.close()

    def _parse_obs(self, msg: dict) -> dict:
        """Extract observation from a game message."""
        return {
            "decision_type": msg.get("decision_type", "unknown"),
            "obs": msg.get("obs", {}),
            "run_context": msg.get("run_context", {}),
        }

    def _parse_episode_end(self, msg: dict) -> dict:
        """Create a terminal observation from episode_end message."""
        return {
            "decision_type": "episode_end",
            "obs": {},
            "run_context": msg.get("run_context", {}),
        }

    def _build_info(self, msg: dict) -> dict:
        return {
            "decision_type": msg.get("decision_type", "unknown"),
        }

    def _encode_action(self, action: dict) -> dict:
        """Encode an action dict into the wire format."""
        return {"type": "action", **action}


def make_random_action(obs: dict) -> dict:
    """Generate a random valid action given an observation. Useful for testing."""
    decision_type = obs.get("decision_type", "unknown")
    obs_data = obs.get("obs", {})

    if decision_type == "combat":
        valid = obs_data.get("valid_actions", {})
        playable = valid.get("playable_cards", [])
        needs_target = set(valid.get("cards_needing_target", []))

        if playable and np.random.random() > 0.3:  # 70% chance to play a card
            card_idx = int(np.random.choice(playable))
            action: dict[str, Any] = {"action_type": "play_card", "card_index": card_idx}

            if card_idx in needs_target:
                enemies = obs_data.get("enemies", [])
                hittable = [e for e in enemies if e.get("is_hittable", False)]
                if hittable:
                    action["target_index"] = int(np.random.randint(len(hittable)))
                else:
                    action["target_index"] = 0

            return action

        return {"action_type": "end_turn"}

    # Non-combat: pick a random option
    options = obs_data.get("options", [])
    can_skip = obs_data.get("can_skip", False)

    if options:
        if can_skip and np.random.random() < 0.2:  # 20% skip chance
            return {"action_type": "skip"}
        idx = int(np.random.randint(len(options)))
        return {"action_type": "select_option", "option_index": idx}

    return {"action_type": "skip"}
