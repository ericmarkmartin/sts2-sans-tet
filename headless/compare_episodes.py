#!/usr/bin/env python3
"""Compare deterministic action and state payloads from two episodes."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def _json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as file:
        return [json.loads(line) for line in file if line.strip()]


def _first_mismatch(left: list[Any], right: list[Any]) -> int | None:
    for index, (left_value, right_value) in enumerate(zip(left, right)):
        if left_value != right_value:
            return index
    return None if len(left) == len(right) else min(len(left), len(right))


def compare_episodes(left: Path, right: Path) -> dict[str, Any]:
    left = left.resolve()
    right = right.resolve()
    left_actions = [record.get("action") for record in _jsonl(left / "actions.jsonl")]
    right_actions = [
        record.get("action") for record in _jsonl(right / "actions.jsonl")
    ]
    left_states = [
        record.get("state")
        for record in _jsonl(left / "results.jsonl")
        if record.get("kind") == "action_result"
    ]
    right_states = [
        record.get("state")
        for record in _jsonl(right / "results.jsonl")
        if record.get("kind") == "action_result"
    ]
    initial_equal = _json(left / "initial.state") == _json(right / "initial.state")
    action_mismatch = _first_mismatch(left_actions, right_actions)
    state_mismatch = _first_mismatch(left_states, right_states)
    left_manifest = _json(left / "manifest.json")
    right_manifest = _json(right / "manifest.json")
    terminal_equal = (
        left_manifest.get("grade") == right_manifest.get("grade")
        and {
            key: left_manifest.get("summary", {}).get(key)
            for key in ("actions", "final_state_type", "act", "floor", "final_hp")
        }
        == {
            key: right_manifest.get("summary", {}).get(key)
            for key in ("actions", "final_state_type", "act", "floor", "final_hp")
        }
    )
    deterministic = (
        initial_equal
        and action_mismatch is None
        and state_mismatch is None
        and terminal_equal
    )
    return {
        "deterministic": deterministic,
        "left": str(left),
        "right": str(right),
        "initial_state_equal": initial_equal,
        "actions": {
            "left": len(left_actions),
            "right": len(right_actions),
            "first_mismatch": action_mismatch,
        },
        "action_result_states": {
            "left": len(left_states),
            "right": len(right_states),
            "first_mismatch": state_mismatch,
        },
        "terminal_summary_equal": terminal_equal,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("left", type=Path)
    parser.add_argument("right", type=Path)
    args = parser.parse_args()
    result = compare_episodes(args.left, args.right)
    print(json.dumps(result, indent=2))
    return 0 if result["deterministic"] else 1


if __name__ == "__main__":
    sys.exit(main())
