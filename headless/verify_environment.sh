#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
game_dir="${STS2_GAME_DIR:-/mnt/c/Program Files (x86)/Steam/steamapps/common/Slay the Spire 2}"
game_data_dir="$game_dir/data_sts2_windows_x86_64"
mods_dir="$game_dir/mods"

required_files=(
  "$game_dir/SlayTheSpire2.exe"
  "$game_data_dir/sts2.dll"
  "$mods_dir/STS2_MCP/manifest.json"
  "$mods_dir/STS2_MCP/STS2_MCP.dll"
  "$mods_dir/STS2_BOOTSTRAP/manifest.json"
  "$mods_dir/STS2_BOOTSTRAP/STS2_BOOTSTRAP.dll"
)

failed=0
for path in "${required_files[@]}"; do
  if [[ -f "$path" ]]; then
    printf 'ok: %s\n' "$path"
  else
    printf 'missing: %s\n' "$path" >&2
    failed=1
  fi
done

for command in nix powershell.exe wslpath; do
  if command -v "$command" >/dev/null; then
    printf 'ok: command %s\n' "$command"
  else
    printf 'missing: command %s\n' "$command" >&2
    failed=1
  fi
done

if ((failed)); then
  exit 1
fi

cd "$repo_dir"
nix develop "path:$repo_dir" -c dotnet --version
nix develop "path:$repo_dir" -c python --version
nix develop "path:$repo_dir" -c ffmpeg -version | sed -n '1p'

printf 'environment ready\n'
