# Portable full-episode rendering

This workflow turns a standalone episode into a muted MP4 containing the full
run: combats, maps, events, rewards, and terminal state. It replays the episode
through the rendered game using the same state-driven translator as semantic
parity checking. A render is successful only when every source action matches.

## One-command workflow

From the repository root:

```bash
./headless/render_full_episode.sh headless/episodes/episode-NNNN
```

The command performs these operations in order:

1. validates the episode JSON/JSONL contract;
2. verifies every installed game/mod file against
   `headless/render-runtime-lock.json` and checks the episode's game DLL hash;
3. injects the episode's profile snapshot, character, ascension, and seed;
4. replays and compares every action while Godot Movie Maker captures an AVI;
5. quits Godot gracefully so the AVI is finalized;
6. transcodes to a muted H.264 MP4 and checks codec, dimensions, and absence of
   an audio stream; and
7. writes hashes and full provenance to `render-manifest.json`.

Output is allocated without overwriting prior work:

```text
headless/render-runs/render-NNNN/
├── episode.avi
├── episode.mp4
├── render-manifest.json
├── ffprobe.json
├── driver.log
├── ffmpeg.log
└── parity/
    ├── parity.json
    ├── actions.jsonl
    ├── states.jsonl
    ├── profile-snapshot.json
    └── game.log
```

The AVI is retained for loss-minimized re-encoding and can be hundreds of
megabytes. Render runs and source episodes are intentionally ignored by Git.

## Defaults and options

The default output is silent 1280×720 H.264 at 30 FPS. Godot uses a dummy
audio driver and FFmpeg removes audio, so neither speaker output nor an MP4
audio track is produced. Instant mechanics preserve proven parity; a
0.35-second dwell before each action makes decision states visible.

```bash
./headless/render_full_episode.sh headless/episodes/episode-NNNN \
  --fps 30 \
  --resolution 1280x720 \
  --action-delay 0.35 \
  --tail-frames 30 \
  --game-speed instant
```

`fast` and `normal` are available for visual experiments but have not yet
passed the same coverage as `instant`. They may require longer action pacing.

## Runtime lock and installation

The checked-in runtime lock pins the executable, original `sts2.dll`, STS2MCP
manifest/DLL, and bootstrap manifest/DLL. A game or mod update must fail closed.
Review the change, rebuild/install the bootstrap if needed, rerun parity, and
then deliberately update the lock hashes. Do not weaken the preflight to accept
an unknown build.

The portable bootstrap suppresses `SaveProgressFile` while a recorded profile
snapshot is injected. The renderer also scans the game log and fails if it
observes a `progress.save` write.

For managed-permission sessions, permanently approve the narrow wrapper:

```text
["./headless/render_full_episode.sh"]
```

The wrapper constrains source episodes to `headless/episodes/`; it does not
accept arbitrary game, executable, or runtime-lock overrides.

## Validated reference

On 2026-08-02, all-unlocks `episode-0014` rendered end-to-end:

- 109/109 standalone actions matched;
- 122 Godot actions, including 13 explicit presentation actions;
- 43.23 seconds at 1280×720 and 30 FPS;
- exactly one H.264 video stream and no audio stream;
- no active-profile progress writes; and
- MP4 SHA-256
  `9faf7c07f25335a6d1661d3d7d6164ca0e8a773ebd0cf8784d26ee1c056a7f20`.

The ignored local artifacts are under `headless/render-runs/render-0003/`.

The longer profile-backed `episode-0012` also passed: 124/124 source actions,
140 Godot actions (16 presentation actions), four combats, a 45.47-second muted
MP4, no profile writes, and SHA-256
`e6d98fffc900b810f4b91208e56bd990552c719ab6cb9826b6be7bb867488e3a`.
Its ignored local artifacts are under `headless/render-runs/render-0004/`.

## Fresh-session prompt

```text
Read headless/FULL_EPISODE_RENDER.md and headless/STS2_CLI_BACKEND.md fully.
Use the pinned sts2-cli checkout to create and validate one portable full-run
episode, or select an existing valid episode under headless/episodes. Run
./headless/render_full_episode.sh on it. Require status=rendered, complete
cross-backend parity, an H.264 stream at the requested dimensions, no audio
stream, no progress.save writes, and matching artifact hashes. Visually sample
early, middle, out-of-combat, and terminal frames. Report clickable paths to
episode.mp4 and render-manifest.json. Do not bypass the runtime lock or claim
success from a merely existing file.
```
