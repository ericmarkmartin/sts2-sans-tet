#!/usr/bin/env python3
"""Render a portable episode trace through Godot and transcode it to MP4."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from headless.render_environment import DEFAULT_GAME_DIR, verify_render_environment
from headless.validate_episode import sha256_file, validate_episode


def allocate_render_dir(root: Path, explicit: Path | None) -> Path:
    if explicit is not None:
        explicit.mkdir(parents=True, exist_ok=True)
        if any(explicit.iterdir()):
            raise RuntimeError(f"Render directory is not empty: {explicit}")
        return explicit.resolve()
    root.mkdir(parents=True, exist_ok=True)
    for index in range(1, 1_000_000):
        candidate = root / f"render-{index:04d}"
        try:
            candidate.mkdir()
            return candidate.resolve()
        except FileExistsError:
            continue
    raise RuntimeError(f"Could not allocate render directory under {root}")


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def run_logged(command: list[str], log_path: Path) -> subprocess.CompletedProcess[str]:
    with log_path.open("w", encoding="utf-8") as log:
        return subprocess.run(
            command,
            cwd=REPO_ROOT,
            text=True,
            stdout=log,
            stderr=subprocess.STDOUT,
            check=False,
        )


def validate_video_probe(
    probe: dict[str, Any], width: int, height: int
) -> dict[str, Any]:
    video_streams = [
        stream
        for stream in probe.get("streams", [])
        if stream.get("codec_type") == "video"
    ]
    if len(video_streams) != 1 or video_streams[0].get("codec_name") != "h264":
        raise ValueError("Rendered MP4 does not contain exactly one H.264 stream")
    if any(
        stream.get("codec_type") == "audio"
        for stream in probe.get("streams", [])
    ):
        raise ValueError("Rendered MP4 unexpectedly contains audio")
    video = video_streams[0]
    if video.get("width") != width or video.get("height") != height:
        raise ValueError("Rendered MP4 dimensions do not match the request")
    return video


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("episode_dir", type=Path)
    parser.add_argument("--game-dir", type=Path, default=DEFAULT_GAME_DIR)
    parser.add_argument(
        "--render-runs-dir", type=Path, default=Path("headless/render-runs")
    )
    parser.add_argument("--port", type=int, default=15526)
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--resolution", default="1280x720")
    parser.add_argument("--action-delay", type=float, default=0.35)
    parser.add_argument("--tail-frames", type=int, default=30)
    parser.add_argument(
        "--game-speed", choices=("instant", "fast", "normal"), default="instant"
    )
    args = parser.parse_args()

    if args.fps <= 0:
        raise ValueError("--fps must be positive")
    if args.action_delay < 0:
        raise ValueError("--action-delay must be nonnegative")
    if not 0 <= args.tail_frames <= 600:
        raise ValueError("--tail-frames must be between 0 and 600")
    resolution_parts = args.resolution.lower().split("x", maxsplit=1)
    if (
        len(resolution_parts) != 2
        or not all(part.isdecimal() and int(part) > 0 for part in resolution_parts)
    ):
        raise ValueError("--resolution must look like 1280x720")
    width, height = (int(value) for value in resolution_parts)

    episode_dir = args.episode_dir.resolve()
    validation = validate_episode(episode_dir)
    if not validation.valid:
        raise RuntimeError(
            "Source episode is invalid:\n" + "\n".join(validation.errors)
        )
    environment = verify_render_environment(
        args.game_dir, episode_dir, port=args.port
    )
    if not environment["valid"]:
        raise RuntimeError(
            "Render environment is invalid:\n" + "\n".join(environment["errors"])
        )

    source_manifest_path = episode_dir / "manifest.json"
    source_manifest = json.loads(source_manifest_path.read_text(encoding="utf-8"))
    render_dir = allocate_render_dir(args.render_runs_dir, None)
    parity_dir = render_dir / "parity"
    avi_path = render_dir / "episode.avi"
    mp4_path = render_dir / "episode.mp4"
    manifest_path = render_dir / "render-manifest.json"
    driver_log_path = render_dir / "driver.log"
    ffmpeg_log_path = render_dir / "ffmpeg.log"
    probe_path = render_dir / "ffprobe.json"
    started_at = datetime.now(timezone.utc).isoformat()
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "status": "running",
        "started_at_utc": started_at,
        "ended_at_utc": None,
        "source": {
            "episode_dir": str(episode_dir),
            "episode_id": source_manifest.get("episode_id"),
            "manifest_sha256": sha256_file(source_manifest_path),
        },
        "settings": {
            "fps": args.fps,
            "resolution": args.resolution,
            "frame_delay_ms": round(1000 / args.fps),
            "action_delay_seconds": args.action_delay,
            "tail_frames": args.tail_frames,
            "game_speed": args.game_speed,
            "muted": True,
        },
        "environment": environment,
        "parity": None,
        "video": None,
        "artifacts": {
            "avi": "episode.avi",
            "mp4": "episode.mp4",
            "parity": "parity/parity.json",
            "driver_log": "driver.log",
            "ffmpeg_log": "ffmpeg.log",
            "ffprobe": "ffprobe.json",
        },
        "failure": None,
    }
    write_json(manifest_path, manifest)

    try:
        replay_command = [
            sys.executable,
            str(REPO_ROOT / "headless" / "replay_trace_godot.py"),
            str(episode_dir),
            "--game",
            str(args.game_dir / "SlayTheSpire2.exe"),
            "--port",
            str(args.port),
            "--parity-dir",
            str(parity_dir),
            "--movie",
            str(avi_path),
            "--fixed-fps",
            str(args.fps),
            "--frame-delay-ms",
            str(round(1000 / args.fps)),
            "--resolution",
            args.resolution,
            "--action-delay",
            str(args.action_delay),
            "--render-tail-frames",
            str(args.tail_frames),
            "--game-speed",
            args.game_speed,
        ]
        replay = run_logged(replay_command, driver_log_path)
        if replay.returncode != 0:
            raise RuntimeError(
                f"Godot replay failed with exit code {replay.returncode}; "
                f"see {driver_log_path}"
            )

        parity_path = parity_dir / "parity.json"
        parity = json.loads(parity_path.read_text(encoding="utf-8"))
        manifest["parity"] = {
            "status": parity.get("status"),
            "source_actions": parity.get("source_actions"),
            "source_actions_consumed": parity.get("source_actions_consumed"),
            "godot_actions": parity.get("godot_actions"),
            "automatic_actions": parity.get("automatic_actions"),
            "sha256": sha256_file(parity_path),
        }
        if parity.get("status") != "matched":
            raise RuntimeError(f"Rendered replay did not match: {parity.get('status')}")
        game_log = (parity_dir / "game.log").read_text(
            encoding="utf-8", errors="replace"
        )
        if re.search(r"Wrote .*progress\.save", game_log):
            raise RuntimeError("Rendered replay wrote to the active progress save")
        if not avi_path.is_file() or avi_path.stat().st_size == 0:
            raise RuntimeError("Godot replay produced no AVI")

        transcode_command = [
            "ffmpeg",
            "-nostdin",
            "-y",
            "-i",
            str(avi_path),
            "-map",
            "0:v:0",
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "20",
            "-pix_fmt",
            "yuv420p",
            "-vf",
            f"scale={width}:{height}:flags=lanczos",
            "-an",
            "-movflags",
            "+faststart",
            str(mp4_path),
        ]
        transcode = run_logged(transcode_command, ffmpeg_log_path)
        if transcode.returncode != 0:
            raise RuntimeError(
                f"FFmpeg failed with exit code {transcode.returncode}; "
                f"see {ffmpeg_log_path}"
            )

        probe_result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_streams",
                "-show_format",
                "-of",
                "json",
                str(mp4_path),
            ],
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        if probe_result.returncode != 0:
            raise RuntimeError(f"ffprobe failed: {probe_result.stderr.strip()}")
        probe = json.loads(probe_result.stdout)
        write_json(probe_path, probe)
        validate_video_probe(probe, width, height)

        manifest["video"] = {
            "duration_seconds": float(probe["format"]["duration"]),
            "avi_size": avi_path.stat().st_size,
            "avi_sha256": sha256_file(avi_path),
            "mp4_size": mp4_path.stat().st_size,
            "mp4_sha256": sha256_file(mp4_path),
            "streams": probe.get("streams", []),
        }
        manifest["status"] = "rendered"
    except Exception as exception:
        manifest["status"] = "failed"
        manifest["failure"] = f"{type(exception).__name__}: {exception}"
        manifest["ended_at_utc"] = datetime.now(timezone.utc).isoformat()
        write_json(manifest_path, manifest)
        raise

    manifest["ended_at_utc"] = datetime.now(timezone.utc).isoformat()
    write_json(manifest_path, manifest)
    print(
        json.dumps(
            {
                "status": manifest["status"],
                "source_episode_id": manifest["source"]["episode_id"],
                "render_dir": str(render_dir),
                "mp4": str(mp4_path),
                "duration_seconds": manifest["video"]["duration_seconds"],
                "mp4_sha256": manifest["video"]["mp4_sha256"],
                "parity": manifest["parity"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
