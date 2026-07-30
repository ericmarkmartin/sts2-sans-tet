#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: ./headless/run_episode.sh --mcr-source PATH [options]
       ./headless/run_episode.sh --replay-episode PATH [options]

Runs one full headless episode using the pinned Nix environment. This launches
the Windows game but does not build or install mods.

Options:
  --mcr-source PATH   Active profile's replays/latest.mcr (full-run mode)
  --replay-episode    Standalone episode to replay for cross-backend parity;
                      does not archive MCRs
  --progress-save     Active Godot progress.save used by a profile-backed trace
  --settle-timeout S  Seconds to wait before declaring divergence (default: 5)
  --seed VALUE        Game seed (default: HEADLESSBENCH)
  --policy-seed N     Policy seed (default: 0)
  --max-actions N     Action cap (default: 5000)
  --episode-dir PATH  Explicit empty output directory
  --dry-run           Print the command without launching the game
  -h, --help          Show this help
EOF
}

repo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
mcr_source=""
seed="HEADLESSBENCH"
policy_seed="0"
max_actions="5000"
episode_dir=""
replay_episode=""
progress_save=""
settle_timeout="5"
dry_run=0

while (($#)); do
  case "$1" in
    --mcr-source) mcr_source="${2:?missing path}"; shift 2 ;;
    --replay-episode) replay_episode="${2:?missing episode path}"; shift 2 ;;
    --progress-save) progress_save="${2:?missing path}"; shift 2 ;;
    --settle-timeout) settle_timeout="${2:?missing timeout}"; shift 2 ;;
    --seed) seed="${2:?missing seed}"; shift 2 ;;
    --policy-seed) policy_seed="${2:?missing policy seed}"; shift 2 ;;
    --max-actions) max_actions="${2:?missing action cap}"; shift 2 ;;
    --episode-dir) episode_dir="${2:?missing episode directory}"; shift 2 ;;
    --dry-run) dry_run=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) printf 'unknown argument: %s\n' "$1" >&2; usage >&2; exit 2 ;;
  esac
done

if [[ -n "$replay_episode" ]]; then
  replay_episode="$(realpath "$replay_episode")"
  case "$replay_episode" in
    "$repo_dir"/headless/episodes/*) ;;
    *)
      printf '%s\n' '--replay-episode must be under headless/episodes' >&2
      exit 2
      ;;
  esac
  command=(
    nix develop "path:$repo_dir" -c python
    "$repo_dir/headless/replay_trace_godot.py"
    "$replay_episode"
    --settle-timeout "$settle_timeout"
  )
  if [[ -n "$progress_save" ]]; then
    progress_save="$(realpath "$progress_save")"
    if [[ ! -f "$progress_save" ]]; then
      printf 'progress save does not exist: %s\n' "$progress_save" >&2
      exit 2
    fi
    command+=(--progress-save "$progress_save")
  fi
elif [[ -z "$mcr_source" ]]; then
  printf '%s\n' '--mcr-source is required' >&2
  exit 2
else
  command=(
    nix develop "path:$repo_dir" -c python
    "$repo_dir/benchmark_headless_episode.py"
    --full-run
    --seed "$seed"
    --policy-seed "$policy_seed"
    --max-actions "$max_actions"
    --mcr-source "$mcr_source"
  )
  if [[ -n "$episode_dir" ]]; then
    command+=(--episode-dir "$episode_dir")
  fi
fi

if ((dry_run)); then
  printf '%q ' "${command[@]}"
  printf '\n'
  exit 0
fi

cd "$repo_dir"
exec "${command[@]}"
