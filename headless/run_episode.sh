#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: ./headless/run_episode.sh --mcr-source PATH [options]

Runs one full headless episode using the pinned Nix environment. This launches
the Windows game but does not build or install mods.

Options:
  --mcr-source PATH   Active profile's replays/latest.mcr (required)
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
dry_run=0

while (($#)); do
  case "$1" in
    --mcr-source) mcr_source="${2:?missing path}"; shift 2 ;;
    --seed) seed="${2:?missing seed}"; shift 2 ;;
    --policy-seed) policy_seed="${2:?missing policy seed}"; shift 2 ;;
    --max-actions) max_actions="${2:?missing action cap}"; shift 2 ;;
    --episode-dir) episode_dir="${2:?missing episode directory}"; shift 2 ;;
    --dry-run) dry_run=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) printf 'unknown argument: %s\n' "$1" >&2; usage >&2; exit 2 ;;
  esac
done

if [[ -z "$mcr_source" ]]; then
  printf '%s\n' '--mcr-source is required' >&2
  exit 2
fi

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

if ((dry_run)); then
  printf '%q ' "${command[@]}"
  printf '\n'
  exit 0
fi

cd "$repo_dir"
exec "${command[@]}"
