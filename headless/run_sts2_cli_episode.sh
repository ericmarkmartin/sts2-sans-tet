#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: ./headless/run_sts2_cli_episode.sh --cli-dir PATH [options]

Records one full standalone sts2-cli run in this repository's episode format.
This does not launch Godot or Steam. With --setup, it reads game assemblies
from --game-data-dir, writes a private patched copy and build outputs only
inside --cli-dir, then runs the episode.

Options:
  --cli-dir PATH          sts2-cli checkout containing lib/ and build output
  --game-data-dir PATH    installed game data directory for dependencies
  --progress-save PATH    Godot progress.save used for unlock/RNG provenance
  --setup                 set up and build the pinned sts2-cli checkout first
  --seed VALUE            game seed (default: HEADLESSBENCH)
  --policy-seed N         baseline-policy seed (default: 0)
  --character NAME        character (default: Ironclad)
  --ascension N           ascension (default: 0)
  --observation-mode MODE human or authoritative (default: human)
  --max-actions N         action cap (default: 5000)
  --self-test             run the repository's headless unit tests and exit
  --validate-only PATH    validate an existing episode and exit
  --compare LEFT RIGHT    compare two episodes for exact determinism and exit
  --dry-run               print setup/run commands without executing them
  -h, --help              show this help
EOF
}

repo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cli_dir=""
game_data_dir=""
progress_save=""
expected_revision="5e3e161a477c826c1010867ec81780dced29f07f"
expected_original_sts2="a1f9e653f1e28e4076558fee1e60d218619cb7e057b887c6417f62c62c6d7a52"
expected_runtime_sts2="7eced881ca7b7a4d4282fa40ff7cf27cc9a4466c4b759c2a2356a4743928fcbe"
setup=0
dry_run=0
self_test=0
validate_only=""
compare_left=""
compare_right=""
seed="HEADLESSBENCH"
policy_seed="0"
character="Ironclad"
ascension="0"
observation_mode="human"
max_actions="5000"

while (($#)); do
  case "$1" in
    --cli-dir) cli_dir="${2:?missing path}"; shift 2 ;;
    --game-data-dir) game_data_dir="${2:?missing path}"; shift 2 ;;
    --progress-save) progress_save="${2:?missing path}"; shift 2 ;;
    --setup) setup=1; shift ;;
    --seed) seed="${2:?missing seed}"; shift 2 ;;
    --policy-seed) policy_seed="${2:?missing policy seed}"; shift 2 ;;
    --character) character="${2:?missing character}"; shift 2 ;;
    --ascension) ascension="${2:?missing ascension}"; shift 2 ;;
    --observation-mode)
      observation_mode="${2:?missing observation mode}"
      shift 2
      ;;
    --max-actions) max_actions="${2:?missing action cap}"; shift 2 ;;
    --self-test) self_test=1; shift ;;
    --validate-only) validate_only="${2:?missing episode path}"; shift 2 ;;
    --compare)
      compare_left="${2:?missing left episode}"
      compare_right="${3:?missing right episode}"
      shift 3
      ;;
    --dry-run) dry_run=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) printf 'unknown argument: %s\n' "$1" >&2; usage >&2; exit 2 ;;
  esac
done

if ((self_test)); then
  cd "$repo_dir"
  exec nix develop "path:$repo_dir" -c python -m unittest discover \
    -s headless/tests -v
fi
if [[ -n "$validate_only" ]]; then
  cd "$repo_dir"
  exec nix develop "path:$repo_dir" -c python \
    "$repo_dir/headless/validate_episode.py" "$validate_only"
fi
if [[ -n "$compare_left" ]]; then
  cd "$repo_dir"
  exec nix develop "path:$repo_dir" -c python \
    "$repo_dir/headless/compare_episodes.py" "$compare_left" "$compare_right"
fi

if [[ -z "$cli_dir" ]]; then
  printf '%s\n' '--cli-dir is required' >&2
  exit 2
fi
cli_dir="$(cd -- "$cli_dir" && pwd)"
actual_revision="$(git -C "$cli_dir" rev-parse HEAD)"
if [[ "$actual_revision" != "$expected_revision" ]]; then
  printf 'unexpected sts2-cli revision\nexpected: %s\nactual:   %s\n' \
    "$expected_revision" "$actual_revision" >&2
  exit 2
fi
if [[ -n "$(git -C "$cli_dir" status --porcelain --untracked-files=no)" ]]; then
  printf 'sts2-cli has tracked worktree changes; refusing an unpinned run\n' >&2
  exit 2
fi
if ((setup)) && [[ -z "$game_data_dir" ]]; then
  printf '%s\n' '--setup requires --game-data-dir' >&2
  exit 2
fi
if [[ -n "$progress_save" ]]; then
  progress_save="$(realpath "$progress_save")"
  if [[ ! -f "$progress_save" ]]; then
    printf 'progress save does not exist: %s\n' "$progress_save" >&2
    exit 2
  fi
fi
if [[ ! "$policy_seed" =~ ^[0-9]+$ || ! "$ascension" =~ ^[0-9]+$ || ! "$max_actions" =~ ^[1-9][0-9]*$ ]]; then
  printf '%s\n' 'policy seed and ascension must be nonnegative integers; max actions must be positive' >&2
  exit 2
fi
case "$character" in
  Ironclad|Silent|Defect|Regent|Necrobinder) ;;
  *) printf 'unsupported character: %s\n' "$character" >&2; exit 2 ;;
esac
case "$observation_mode" in
  human|authoritative) ;;
  *) printf 'unsupported observation mode: %s\n' "$observation_mode" >&2; exit 2 ;;
esac

cli_dll="$cli_dir/src/Sts2Headless/bin/Debug/net9.0/Sts2Headless.dll"
cli_lib="$cli_dir/lib"

setup_command=()
build_command=()
if ((setup)); then
  setup_command=(
    nix develop "path:$cli_dir" -c
    "$cli_dir/setup.sh" "$game_data_dir"
  )
else
  build_command=(
    nix develop "path:$cli_dir" -c dotnet build
    "$cli_dir/src/Sts2Headless/Sts2Headless.csproj" --no-restore
  )
fi

command=(
  nix develop "path:$repo_dir" -c python
  "$repo_dir/headless/sts2_cli_episode.py"
  --cli-dll "$cli_dll"
  --cli-lib "$cli_lib"
  --seed "$seed"
  --policy-seed "$policy_seed"
  --character "$character"
  --ascension "$ascension"
  --observation-mode "$observation_mode"
  --max-actions "$max_actions"
)
if [[ -n "$game_data_dir" ]]; then
  command+=(--game-data-dir "$game_data_dir")
fi
if [[ -n "$progress_save" ]]; then
  command+=(--progress-save "$progress_save")
fi

if ((dry_run)); then
  if ((${#setup_command[@]})); then
    printf 'setup: '
    printf '%q ' "${setup_command[@]}"
    printf '\n'
  fi
  if ((${#build_command[@]})); then
    printf 'build: '
    printf '%q ' "${build_command[@]}"
    printf '\n'
  fi
  printf 'run: '
  printf '%q ' "${command[@]}"
  printf '\n'
  exit 0
fi

if ((${#setup_command[@]})); then
  printf '%s\n' \
    "Setting up pinned sts2-cli revision $expected_revision" \
    "Read-only source: $game_data_dir" \
    "Writable checkout: $cli_dir"
  (
    cd "$cli_dir"
    "${setup_command[@]}"
    "$cli_dir/scripts/verify_game_libs.sh"
  )
else
  "${build_command[@]}"
fi

actual_original_sts2="$(sha256sum "$cli_lib/sts2.dll.original" | cut -d' ' -f1)"
actual_runtime_sts2="$(sha256sum "$cli_lib/sts2.dll" | cut -d' ' -f1)"
if [[ "$actual_original_sts2" != "$expected_original_sts2" ||
      "$actual_runtime_sts2" != "$expected_runtime_sts2" ]]; then
  printf 'sts2 DLL provenance mismatch\noriginal: %s\nruntime:  %s\n' \
    "$actual_original_sts2" "$actual_runtime_sts2" >&2
  exit 2
fi

cd "$repo_dir"
exec "${command[@]}"
