#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: ./headless/render_episode_replays.sh EPISODE_DIR [options]

Renders archived combat MCRs through the Windows game, transcodes the Godot AVI
captures to H.264/AAC MP4, and verifies the resulting streams. Existing MP4s
are skipped unless --force is given. AVI intermediates are always retained.

Options:
  --combat N          Render one combat index; repeat for several (default: all)
  --force             Replace existing AVI and MP4 outputs
  --dry-run           Print commands without launching or writing outputs
  -h, --help          Show this help
EOF
}

repo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
episode_dir=""
force=0
dry_run=0
combats=()

while (($#)); do
  case "$1" in
    --combat) combats+=("${2:?missing combat index}"); shift 2 ;;
    --force) force=1; shift ;;
    --dry-run) dry_run=1; shift ;;
    -h|--help) usage; exit 0 ;;
    -*)
      printf 'unknown argument: %s\n' "$1" >&2
      usage >&2
      exit 2
      ;;
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
if [[ ! -f "$episode_dir/manifest.json" ]]; then
  printf 'manifest not found: %s\n' "$episode_dir/manifest.json" >&2
  exit 1
fi

if ((${#combats[@]} == 0)); then
  while IFS= read -r replay; do
    combats+=("$replay")
  done < <(
    nix develop "path:$repo_dir" -c python -c \
      'import json,sys; m=json.load(open(sys.argv[1])); print(*[r["combat_index"] for r in m["artifacts"]["combat_replays"]], sep="\n")' \
      "$episode_dir/manifest.json"
  )
fi

mkdir_command=(mkdir -p "$episode_dir/videos")
if ((dry_run)); then
  printf '%q ' "${mkdir_command[@]}"
  printf '\n'
else
  "${mkdir_command[@]}"
fi

script_path="$(wslpath -w "$repo_dir/headless/render_combat_replay.ps1")"
for combat in "${combats[@]}"; do
  if [[ ! "$combat" =~ ^[0-9]+$ ]]; then
    printf 'invalid combat index: %s\n' "$combat" >&2
    exit 2
  fi
  printf -v stem 'combat-%03d' "$combat"
  replay="$episode_dir/replays/$stem.mcr"
  avi="$episode_dir/videos/$stem.avi"
  mp4="$episode_dir/videos/$stem.mp4"
  if [[ ! -s "$replay" ]]; then
    printf 'replay not found or empty: %s\n' "$replay" >&2
    exit 1
  fi
  if [[ -s "$mp4" && "$force" -eq 0 ]]; then
    printf 'skip existing: %s\n' "$mp4"
    continue
  fi

  replay_windows="$(wslpath -w "$replay")"
  avi_windows="$(wslpath -w "$avi")"
  render_command=(
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$script_path"
    -ReplayPath "$replay_windows" -MoviePath "$avi_windows"
  )
  transcode_command=(
    nix develop "path:$repo_dir" -c ffmpeg -y -i "$avi"
    -c:v libx264 -preset medium -crf 20 -pix_fmt yuv420p
    -c:a aac -b:a 192k -movflags +faststart "$mp4"
  )
  verify_command=(
    nix develop "path:$repo_dir" -c ffprobe -v error
    -show_entries format=filename,duration,size
    -show_entries stream=codec_name,codec_type,width,height,r_frame_rate
    -of compact=p=0:nk=1 "$mp4"
  )

  if ((dry_run)); then
    printf '%q ' "${render_command[@]}"
    printf '\n'
    printf '%q ' "${transcode_command[@]}"
    printf '\n'
    printf '%q ' "${verify_command[@]}"
    printf '\n'
    continue
  fi
  if [[ ! -s "$avi" || "$force" -eq 1 ]]; then
    "${render_command[@]}"
  fi
  "${transcode_command[@]}"
  "${verify_command[@]}"
done
