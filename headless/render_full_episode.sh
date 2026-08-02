#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: ./headless/render_full_episode.sh EPISODE_DIR [options]

Replays a portable standalone episode in the rendered game, requires complete
semantic parity, captures a Godot Movie Maker AVI, transcodes it to H.264 MP4,
removes audio, and writes a provenance manifest. Outputs are allocated under
headless/render-runs/ by default.

Options:
  --fps N             Output frame rate (default: 30)
  --resolution WxH    Output dimensions (default: 1280x720)
  --action-delay S    Visible dwell before each action (default: 0.35)
  --tail-frames N     Final-state frames before graceful quit (default: 30)
  --game-speed MODE   instant, fast, or normal (default: instant)
  -h, --help          Show this help
EOF
}

repo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
episode_dir=""
args=()

while (($#)); do
  case "$1" in
    --fps|--resolution|--action-delay|--tail-frames|--game-speed)
      args+=("$1" "${2:?missing value for $1}")
      shift 2
      ;;
    -h|--help) usage; exit 0 ;;
    -*) printf 'unknown argument: %s\n' "$1" >&2; usage >&2; exit 2 ;;
    *)
      if [[ -n "$episode_dir" ]]; then
        printf 'only one episode directory may be supplied\n' >&2
        exit 2
      fi
      episode_dir="$1"
      shift
      ;;
  esac
done

if [[ -z "$episode_dir" ]]; then
  usage >&2
  exit 2
fi
episode_dir="$(realpath "$episode_dir")"
case "$episode_dir" in
  "$repo_dir"/headless/episodes/*) ;;
  *)
    printf '%s\n' 'episode must be under headless/episodes' >&2
    exit 2
    ;;
esac

cd "$repo_dir"
exec nix develop "path:$repo_dir" -c python \
  "$repo_dir/headless/render_full_episode.py" "$episode_dir" "${args[@]}"
