# End-to-end headless simulation and replay runbook

This is the canonical procedure for running one deterministic run from act
entry through game over under Godot headless and preserving its artifacts:

- the initial full state;
- append-only requested actions and resulting states;
- a versioned manifest; and
- one built-in binary replay (`.mcr`) for each completed combat, copied before
  `latest.mcr` can be overwritten.

This procedure has been validated against Slay the Spire 2 `v0.107.1`, release
commit `59260271`, on Windows launched from WSL2.

## What "replay" means here

The headless episode runner automatically archives a built-in `.mcr` for each
combat; it does not render video during simulation. The companion bootstrap mod
can subsequently load one of those `.mcr` files in a matching rendered build,
and Godot movie capture plus FFmpeg can turn that playback into an MP4.

This post-hoc render path has been validated for all three won combats in
`episode-0003`. It is currently a two-stage per-combat procedure rather than a
single episode-level command. Also, the current `.mcr` artifacts contain
actions but no checksum samples: playback completes, but is not
checksum-validated. See `headless/HANDOFF.md` for current results and caveats.

## Prerequisites

1. Run from the repository root in WSL2.
2. The Windows Steam installation of Slay the Spire 2 must exist. The default
   expected path is:

   ```text
   /mnt/c/Program Files (x86)/Steam/steamapps/common/Slay the Spire 2
   ```

3. The game must have modding enabled and the mod-consent dialog accepted at
   least once in a normal rendered launch.
4. A game-compatible STS2MCP build must be installed as mod `STS2_MCP`.
   For `v0.107.1`, the compatibility changes are recorded in
   `patches/sts2mcp-v0.107.1.patch`.
5. The companion mod from `godot_bootstrap/` must be installed as
   `STS2_BOOTSTRAP`.
6. Nothing else may own STS2MCP port `15526`. The runner checks this and fails
   before launching if the port is occupied.

## 1. Verify the development shell

```bash
nix develop "path:$PWD" -c dotnet --version
nix develop "path:$PWD" -c python --version
```

Expected major versions are .NET 9 and Python 3.11.

## 2. Build and install the bootstrap mod

```bash
nix develop "path:$PWD" -c dotnet build godot_bootstrap \
  -p:STS2GameDataDir="/mnt/c/Program Files (x86)/Steam/steamapps/common/Slay the Spire 2/data_sts2_windows_x86_64"

mkdir -p "/mnt/c/Program Files (x86)/Steam/steamapps/common/Slay the Spire 2/mods/STS2_BOOTSTRAP"
cp godot_bootstrap/manifest.json \
  "/mnt/c/Program Files (x86)/Steam/steamapps/common/Slay the Spire 2/mods/STS2_BOOTSTRAP/manifest.json"
cp godot_bootstrap/bin/Debug/net9.0/STS2Bootstrap.dll \
  "/mnt/c/Program Files (x86)/Steam/steamapps/common/Slay the Spire 2/mods/STS2_BOOTSTRAP/STS2_BOOTSTRAP.dll"
```

Verify both required manifests and DLLs:

```bash
ls -l \
  "/mnt/c/Program Files (x86)/Steam/steamapps/common/Slay the Spire 2/mods/STS2_MCP/manifest.json" \
  "/mnt/c/Program Files (x86)/Steam/steamapps/common/Slay the Spire 2/mods/STS2_MCP/STS2_MCP.dll" \
  "/mnt/c/Program Files (x86)/Steam/steamapps/common/Slay the Spire 2/mods/STS2_BOOTSTRAP/manifest.json" \
  "/mnt/c/Program Files (x86)/Steam/steamapps/common/Slay the Spire 2/mods/STS2_BOOTSTRAP/STS2_BOOTSTRAP.dll"
```

If STS2MCP is absent or does not build against `v0.107.1`, use the compatible
fork, apply `patches/sts2mcp-v0.107.1.patch` once, build it against the same game
data directory, and install its manifest and DLL as `STS2_MCP`. Do not apply the
patch blindly to a dirty checkout; first use `git apply --check`.

## 3. Resolve the active modded replay path

The game log reports a profile such as:

```text
user://steam/<steam-id>/modded/profile1
```

The corresponding WSL replay source is:

```text
/mnt/c/Users/<windows-user>/AppData/Roaming/SlayTheSpire2/steam/<steam-id>/modded/profile1/replays/latest.mcr
```

Find existing candidates with:

```bash
find /mnt/c/Users \
  -path '*/AppData/Roaming/SlayTheSpire2/*/*/modded/profile*/replays/latest.mcr' \
  -print
```

If there is no existing `latest.mcr`, inspect a prior game log for
`Profile-scoped data path initialized`, then construct the path above. It is
valid to pass a not-yet-created `latest.mcr`; the runner waits for the current
combat to create it.

## 4. Run one full episode and archive every combat replay

Replace `<mcr-source>` with the exact path resolved in step 3:

```bash
nix develop "path:$PWD" -c python benchmark_headless_episode.py \
  --seed HEADLESSBENCH \
  --policy-seed 0 \
  --full-run \
  --max-actions 5000 \
  --mcr-source "<mcr-source>"
```

By default the runner atomically allocates the first unused directory under
`headless/episodes/`, beginning with `episode-0001`. Pass
`--episode-dir <path>` only when an explicit empty destination is required; the
runner refuses to overwrite a non-empty directory.

The runner:

1. verifies port `15526` is unused;
2. launches exactly one Windows game process with
   `--headless --audio-driver Dummy --bootstrap`;
3. enters a normal act rather than a detached debug combat;
4. drives initial choices, map, combat, rewards, events, rest sites, shops, and
   other supported run states until game over or `--max-actions`;
5. records the initial state, every requested action, every action result/full
   state, and asynchronous state transitions;
6. explicitly flushes the built-in replay after each combat, including loss;
7. copies and hashes each `.mcr`; and
8. writes version/build metadata and terminates the exact Windows process it
   launched, including on failure.

## 5. Required success criteria

The command must exit zero and its JSON summary must contain:

- `"final_state_type": "game_over"` for an episode that naturally completed;
- a non-empty `"combat_replays"` array;
- a replay `"size"` greater than zero;
- a 64-character `"sha256"`; and
- replay paths such as `replays/combat-000.mcr`.

For the first run, the expected layout is:

```text
headless/episodes/episode-0001/
├── initial.state
├── actions.jsonl
├── results.jsonl
├── manifest.json
├── game.log
└── replays/
    ├── combat-000.mcr
    └── ...
```

`actions.jsonl` contains requested agent actions. `results.jsonl` contains
`action_result` records keyed by action index and `async_state` records for
unprompted transitions such as enemy-turn completion or game over.
`manifest.json` contains seeds, timestamps, outcome, release/commit/engine
versions, hashes of `sts2.dll` and both mod DLLs, and all replay paths/hashes.
Its episodic grade is deliberately binary: terminal loss is `0`, terminal win
is `1`, and an action-capped or failed nonterminal episode is `null` rather
than being mislabeled as a loss.

Verify the episode directory reported by the command (shown here as
`episode-0001`):

```bash
episode_dir=headless/episodes/episode-0001
test -s "$episode_dir/initial.state"
test -s "$episode_dir/actions.jsonl"
test -s "$episode_dir/results.jsonl"
test -s "$episode_dir/manifest.json"
test -s "$episode_dir/game.log"
test -s "$episode_dir/replays/combat-000.mcr"
sha256sum "$episode_dir/replays/"*.mcr
```

Each replay SHA-256 in `manifest.json` must match `sha256sum`.

## Failure recovery

- **Port already accepting connections:** inspect and stop only the stale
  `SlayTheSpire2` process from an earlier run. Do not kill unrelated processes.
- **Run never becomes ready:** inspect the episode's `game.log`. Confirm that
  both mods loaded, STS2MCP
  bound port `15526`, and `Creating NCombatRoom` appears.
- **Fresh replay did not appear:** confirm the `--mcr-source` points to the same
  modded profile printed in the current game log.
- **STS2MCP compilation errors:** verify the game version and apply the
  version-scoped compatibility patch only to the matching fork revision.
- **A prior failed WSL launcher left a process:** the current runner uses a
  Windows PID file and targeted `Stop-Process`; if cleanup is still required,
  resolve exact PIDs and start times before stopping anything.

## Prompt for a fresh Codex session

Copy this prompt from the repository root:

```text
Follow headless/END_TO_END_REPLAY.md exactly. Verify the installed game and both
mods, building/installing the bootstrap mod if necessary. Resolve the active
modded profile's latest.mcr path from local files or the game log. Run one full
HEADLESSBENCH episode with policy seed 0 from act entry through game over,
archiving every built-in combat replay. Verify initial.state, actions.jsonl,
results.jsonl, manifest version/build hashes, game.log, and every .mcr SHA-256
linkage. Then render each archived combat replay with
headless/render_combat_replay.ps1, transcode each AVI to H.264/AAC MP4 with
FFmpeg, use ffprobe plus representative extracted frames to validate each
output, and report the clickable episode directory. State explicitly whether
the source replay contains checksum samples. Preserve unrelated changes and
stop only the exact game process launched by the runner.
```
