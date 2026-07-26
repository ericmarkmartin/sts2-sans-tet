# Headless simulation and replay handoff

Status as of 2026-07-26 on branch `headless-godot-bootstrap`.

## What works

- A pinned `nix develop` shell supplies .NET 9, Python 3.11, `uv`, and FFmpeg.
- The real game runs under Godot `--headless --audio-driver Dummy`.
- The bootstrap mod enters deterministic combat or a normal full run without
  menu automation.
- `benchmark_headless_episode.py` drives full runs through map, event, combat,
  reward, rest-site, shop, and game-over states supported by STS2MCP.
- Each episode is self-contained:

  ```text
  episode-NNNN/
  ├── initial.state
  ├── actions.jsonl
  ├── results.jsonl
  ├── manifest.json
  ├── game.log
  └── replays/combat-NNN.mcr
  ```

- Episode grades are binary: terminal loss `0`, terminal win `1`, incomplete
  `null`.
- The runner owns and terminates the exact Windows game process it launches,
  refuses an occupied bridge port, and preserves logs on failure.
- A tactical policy run reached floor 8, won three combats, and died in its
  fourth combat. Its artifacts are in `headless/episodes/episode-0003/`.
- The bootstrap mod can load a built-in `.mcr`, play it in the rendered game,
  and quit after a short final-frame tail.
- Godot movie capture plus FFmpeg produces H.264/AAC MP4s. The three won
  combats from episode 0003 were rendered and visually checked:

  | Replay | MP4 duration | MP4 size |
  | --- | ---: | ---: |
  | `combat-000.mcr` | 36.683 s | 40,150,262 bytes |
  | `combat-001.mcr` | 15.150 s | 15,114,581 bytes |
  | `combat-002.mcr` | 19.150 s | 20,986,135 bytes |

  Outputs are under `headless/episodes/episode-0003/videos/`.

## Important limitations

- The current `.mcr` files have internal actions but no checksum samples.
  Rendered playback reaches the recorded victories, but it is action-replayed,
  not checksum-validated. The game consequently logs noisy "checksum does not
  exist in replay data" divergence messages.
- `.mcr` is combat-only. We do not yet have a renderer for map, reward, event,
  shop, or rest-site decisions. Those transitions are preserved in episode
  JSONL, but cannot yet be fed into the game's built-in replay player.
- MCR-to-MP4 is currently two stages: `render_combat_replay.ps1` creates a
  large MJPEG/PCM AVI, then FFmpeg transcodes it. There is no single
  episode-level command, manifest video entry, or automatic intermediate
  cleanup yet.
- Saved display settings override the requested 1280x720 capture size, so the
  current outputs are 2560x1440 at 60 FPS.
- Audio tracks exist, but combats 001 and 002 contain very little encoded audio
  and may effectively be silent. Audio behavior needs an explicit check.
- The whole implementation is uncommitted. Preserve unrelated changes and make
  a reviewed checkpoint commit before risky refactors.

## Recommended next work

### Safe workspace-only work

These tasks need no game launch and should not require permission prompts:

1. Add tests for episode allocation, JSONL linkage, binary grading, tactical
   action selection, and manifest validation.
2. Add an offline episode validator that checks required files, JSONL indices,
   replay/video hashes, terminal outcome, and grade consistency.
3. Refactor the runner into smaller policy, artifact, process, and protocol
   modules while retaining CLI compatibility.
4. Update all documentation and the fresh-session prompt to cover MP4 output.
5. Add schemas or typed structures for manifest, action, and result records.
6. Review the dirty worktree, separate generated artifacts from source, and
   prepare a coherent checkpoint commit.

### One reusable approval per command family

Package external operations behind stable repository scripts, then approve the
script paths rather than every expanded command:

1. `headless/run_episode.sh`: verify/build/install mods and run one episode.
2. `headless/render_episode_replays.sh`: render selected MCRs, transcode,
   validate, and update the manifest.
3. `headless/verify_environment.sh`: read-only game/mod/version checks.

Good reusable approval prefixes after those scripts are reviewed:

```text
["./headless/verify_environment.sh"]
["./headless/run_episode.sh"]
["./headless/render_episode_replays.sh"]
```

The first script should be read-only. The latter two legitimately launch the
Windows game; `run_episode.sh` may also install rebuilt mod DLLs. Keep those
effects explicit in `--help`.

### Game-facing investigations

These need the rendered game and therefore at least one reusable approval:

1. Build the episode-level MCR-to-MP4 command and test it on a fresh episode.
2. Determine why replay checksum data is absent and either record it or label
   the manifest's replay-validation level explicitly.
3. Force a predictable capture resolution after saved settings load.
4. Verify and fix replay audio.
5. Design non-combat visual replay. The likely approach is a new episode-trace
   playback mode that starts a pinned run from `initial.state` and replays
   external actions, rather than extending the combat-only MCR format.
6. Benchmark capture speed, MP4 size, and quality at 720p/30, 1080p/30, and
   1440p/60.

## Suggested autonomous sequence

1. Finish documentation and add the offline validator and tests.
2. Add the three stable wrapper scripts with dry-run and `--help` support.
3. Review the complete diff and create a checkpoint commit on the existing
   branch.
4. With one approval for the render wrapper, automate episode-level MP4
   generation and manifest updates.
5. Investigate missing checksums and non-combat replay without changing the
   episode artifact contract.

At every stage, avoid deleting AVI intermediates or modifying installed game
files unless the command and its reported effects explicitly say so.
