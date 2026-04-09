#!/usr/bin/env python3
"""Test script: run a random agent against the STS2 RL Bridge.

Usage:
    1. Start this script: python test_random_agent.py
    2. Launch STS2 with: SlayTheSpire2.exe --autoslay
       (with rl_bridge mod installed in mods/ directory)
    3. Watch the random agent play!
"""

import logging
import sys

from sts2_rl.connection import ConnectionServer
from sts2_rl.env import make_random_action
from sts2_rl.reward import compute_reward

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("test_random_agent")


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 19720

    server = ConnectionServer(port=port)
    server.start()
    server.wait_for_connection()

    episode = 0
    step = 0
    total_reward = 0.0
    prev_run_context = None

    try:
        while True:
            msg = server.receive()
            msg_type = msg.get("type", "unknown")

            if msg_type == "episode_end":
                reward = compute_reward(msg, prev_run_context)
                total_reward += reward
                episode += 1
                result = msg.get("result", "unknown")
                floor = msg.get("floor_reached", 0)
                logger.info(
                    f"Episode {episode} ended: {result} at floor {floor} "
                    f"| steps={step} reward={total_reward:.2f}"
                )
                server.send({"type": "reset_ack"})
                step = 0
                total_reward = 0.0
                prev_run_context = None
                continue

            if msg_type != "obs":
                logger.warning(f"Unexpected message type: {msg_type}")
                continue

            step += 1
            decision_type = msg.get("decision_type", "?")
            reward = compute_reward(msg, prev_run_context)
            total_reward += reward
            prev_run_context = msg.get("run_context", {})

            obs = {
                "decision_type": decision_type,
                "obs": msg.get("obs", {}),
                "run_context": msg.get("run_context", {}),
            }

            action = make_random_action(obs)

            if step % 10 == 0 or decision_type != "combat":
                hp = msg.get("run_context", {}).get("hp", "?")
                floor = msg.get("run_context", {}).get("total_floor", "?")
                logger.info(
                    f"Step {step} [{decision_type}] HP={hp} Floor={floor} "
                    f"-> {action.get('action_type', '?')}"
                )

            server.send({"type": "action", **action})

    except KeyboardInterrupt:
        logger.info("Interrupted")
    except ConnectionError as e:
        logger.info(f"Game disconnected: {e}")
    finally:
        server.close()


if __name__ == "__main__":
    main()
