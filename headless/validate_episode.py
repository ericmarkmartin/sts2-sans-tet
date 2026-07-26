#!/usr/bin/env python3
"""Validate an archived headless episode without launching the game."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ValidationReport:
    episode_dir: Path
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    actions: int = 0
    results: int = 0
    replays: int = 0

    @property
    def valid(self) -> bool:
        return not self.errors

    def as_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "episode_dir": str(self.episode_dir),
            "errors": self.errors,
            "warnings": self.warnings,
            "counts": {
                "actions": self.actions,
                "results": self.results,
                "combat_replays": self.replays,
            },
        }


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path, report: ValidationReport) -> Any | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        report.errors.append(f"missing required file: {path.name}")
    except (OSError, json.JSONDecodeError) as exception:
        report.errors.append(f"invalid {path.name}: {exception}")
    return None


def read_jsonl(path: Path, report: ValidationReport) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    try:
        with path.open(encoding="utf-8") as file:
            for line_number, line in enumerate(file, 1):
                if not line.strip():
                    report.errors.append(
                        f"{path.name}:{line_number}: blank JSONL record"
                    )
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError as exception:
                    report.errors.append(
                        f"{path.name}:{line_number}: invalid JSON: {exception}"
                    )
                    continue
                if not isinstance(record, dict):
                    report.errors.append(
                        f"{path.name}:{line_number}: record is not an object"
                    )
                    continue
                records.append(record)
    except FileNotFoundError:
        report.errors.append(f"missing required file: {path.name}")
    except OSError as exception:
        report.errors.append(f"cannot read {path.name}: {exception}")
    return records


def resolve_artifact(
    episode_dir: Path, relative: Any, label: str, report: ValidationReport
) -> Path | None:
    if not isinstance(relative, str) or not relative:
        report.errors.append(f"{label} path must be a non-empty string")
        return None
    candidate = (episode_dir / relative).resolve()
    try:
        candidate.relative_to(episode_dir.resolve())
    except ValueError:
        report.errors.append(f"{label} escapes episode directory: {relative}")
        return None
    return candidate


def validate_grade(manifest: dict[str, Any], report: ValidationReport) -> None:
    grade = manifest.get("grade")
    if not isinstance(grade, dict):
        report.errors.append("manifest grade must be an object")
        return
    outcome = grade.get("outcome")
    terminal = grade.get("terminal")
    value = grade.get("value")
    expected = {"loss": 0, "win": 1, "incomplete": None}
    if outcome not in expected:
        report.errors.append(f"unknown grade outcome: {outcome!r}")
    elif value != expected[outcome]:
        report.errors.append(
            f"grade {value!r} does not match outcome {outcome!r}"
        )
    if not isinstance(terminal, bool):
        report.errors.append("grade terminal must be boolean")
    elif terminal != (outcome in {"loss", "win"}):
        report.errors.append(
            f"grade terminal={terminal} is inconsistent with outcome {outcome!r}"
        )
    summary = manifest.get("summary", {})
    if isinstance(summary, dict):
        if summary.get("outcome") != outcome:
            report.errors.append("summary outcome does not match grade outcome")
        if summary.get("grade") != value:
            report.errors.append("summary grade does not match manifest grade")
        final_state = summary.get("final_state_type")
        if terminal != (final_state == "game_over"):
            report.errors.append(
                "terminal grade is inconsistent with summary final_state_type"
            )


def validate_episode(episode_dir: Path) -> ValidationReport:
    episode_dir = episode_dir.resolve()
    report = ValidationReport(episode_dir)
    manifest_value = read_json(episode_dir / "manifest.json", report)
    initial_state = read_json(episode_dir / "initial.state", report)
    actions = read_jsonl(episode_dir / "actions.jsonl", report)
    results = read_jsonl(episode_dir / "results.jsonl", report)
    report.actions = len(actions)
    report.results = len(results)

    if not isinstance(manifest_value, dict):
        return report
    manifest = manifest_value
    if manifest.get("schema_version") != 1:
        report.errors.append(
            f"unsupported manifest schema_version: {manifest.get('schema_version')!r}"
        )
    if manifest.get("episode_id") != episode_dir.name:
        report.errors.append("manifest episode_id does not match directory name")
    if not isinstance(initial_state, dict):
        report.errors.append("initial.state must contain a JSON object")

    indexes = [record.get("index") for record in actions]
    expected_indexes = list(range(len(actions)))
    if indexes != expected_indexes:
        report.errors.append(
            "action indexes must be unique, contiguous, and start at zero"
        )
    for index, record in enumerate(actions):
        if not isinstance(record.get("action"), dict):
            report.errors.append(f"action {index} has no action object")

    action_result_indexes: list[Any] = []
    for result_number, record in enumerate(results):
        kind = record.get("kind")
        if kind == "action_result":
            action_result_indexes.append(record.get("index"))
            if not isinstance(record.get("state"), dict):
                report.errors.append(
                    f"result record {result_number} has no state object"
                )
        elif kind == "async_state":
            after = record.get("after_action_index")
            if after is not None and (
                not isinstance(after, int) or after < 0 or after >= len(actions)
            ):
                report.errors.append(
                    f"result record {result_number} has invalid "
                    f"after_action_index {after!r}"
                )
            if not isinstance(record.get("state"), dict):
                report.errors.append(
                    f"result record {result_number} has no state object"
                )
        elif kind == "combat_replay":
            # Older traces may include replay linkage records. The manifest is
            # authoritative for replay artifact validation.
            continue
        else:
            report.errors.append(
                f"result record {result_number} has unknown kind {kind!r}"
            )
    if sorted(action_result_indexes) != expected_indexes:
        report.errors.append("each action must have exactly one action_result")

    summary = manifest.get("summary")
    if not isinstance(summary, dict):
        report.errors.append("manifest summary must be an object")
    elif summary.get("actions") != len(actions):
        report.errors.append(
            f"summary actions={summary.get('actions')!r} but JSONL has {len(actions)}"
        )
    validate_grade(manifest, report)

    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, dict):
        report.errors.append("manifest artifacts must be an object")
        return report
    expected_artifacts = {
        "initial_state": "initial.state",
        "actions": "actions.jsonl",
        "results": "results.jsonl",
        "game_log": "game.log",
    }
    for key, default in expected_artifacts.items():
        artifact = resolve_artifact(
            episode_dir, artifacts.get(key, default), f"artifact {key}", report
        )
        if artifact is not None and not artifact.is_file():
            report.errors.append(f"missing artifact {key}: {artifact.name}")

    replay_records = artifacts.get("combat_replays", [])
    if not isinstance(replay_records, list):
        report.errors.append("artifacts combat_replays must be an array")
        return report
    report.replays = len(replay_records)
    replay_indexes: list[Any] = []
    for position, replay in enumerate(replay_records):
        label = f"combat replay {position}"
        if not isinstance(replay, dict):
            report.errors.append(f"{label} must be an object")
            continue
        replay_indexes.append(replay.get("combat_index"))
        path = resolve_artifact(episode_dir, replay.get("path"), label, report)
        if path is None:
            continue
        if not path.is_file():
            report.errors.append(f"{label} is missing: {replay.get('path')}")
            continue
        actual_size = path.stat().st_size
        if replay.get("size") != actual_size:
            report.errors.append(
                f"{label} size mismatch: manifest={replay.get('size')!r}, "
                f"actual={actual_size}"
            )
        actual_hash = sha256_file(path)
        if replay.get("sha256") != actual_hash:
            report.errors.append(f"{label} SHA-256 mismatch")
    if replay_indexes != list(range(len(replay_records))):
        report.errors.append(
            "combat replay indexes must be contiguous and start at zero"
        )
    if not replay_records:
        report.warnings.append("episode contains no archived combat replays")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("episode_dir", type=Path)
    parser.add_argument(
        "--json", action="store_true", help="emit a machine-readable report"
    )
    args = parser.parse_args()
    report = validate_episode(args.episode_dir)
    if args.json:
        print(json.dumps(report.as_dict(), indent=2))
    else:
        status = "VALID" if report.valid else "INVALID"
        print(f"{status}: {report.episode_dir}")
        for error in report.errors:
            print(f"error: {error}")
        for warning in report.warnings:
            print(f"warning: {warning}")
        print(
            f"actions={report.actions} results={report.results} "
            f"combat_replays={report.replays}"
        )
    return 0 if report.valid else 1


if __name__ == "__main__":
    sys.exit(main())
