"""Reward computation from observation deltas."""

from __future__ import annotations


def compute_reward(msg: dict, prev_run_context: dict | None) -> float:
    """Compute reward from the current message and previous run context.

    Rewards are kept simple and sparse for initial training:
    - Small per-step cost to encourage efficiency
    - HP delta signal (losing HP is bad)
    - Combat/run outcome bonuses
    """
    msg_type = msg.get("type", "obs")
    run_ctx = msg.get("run_context", {})

    if msg_type == "episode_end":
        result = msg.get("result", "death")
        floor = msg.get("floor_reached", 0)

        if result == "victory":
            return 100.0 + floor * 0.5
        elif result == "death":
            return -10.0 + floor * 0.5  # reward for getting further even if dying
        return 0.0

    if prev_run_context is None:
        return 0.0

    reward = 0.0

    # Floor progress
    prev_floor = prev_run_context.get("total_floor", 0)
    curr_floor = run_ctx.get("total_floor", 0)
    floor_delta = curr_floor - prev_floor
    reward += floor_delta * 1.0

    # HP delta (small signal)
    prev_hp = prev_run_context.get("hp", 0)
    curr_hp = run_ctx.get("hp", 0)
    hp_delta = curr_hp - prev_hp
    reward += hp_delta * 0.01

    # Small step cost to encourage faster decisions
    reward -= 0.001

    return reward
