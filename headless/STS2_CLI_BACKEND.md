# Standalone full-run backend (`sts2-cli`)

This is the shortest path from a fresh Codex session to a recorded full run
without launching Godot or Steam. It uses our compatibility branch of
[`ericmarkmartin/sts2-cli`](https://github.com/ericmarkmartin/sts2-cli),
pinned here to commit `5e3e161`.

The output uses the same episode contract as the Godot-headless runner:

```text
episode-NNNN/
├── initial.state
├── actions.jsonl
├── results.jsonl
├── manifest.json
└── game.log
```

The standalone backend does not currently produce `.mcr` combat replays.
Its episode actions can now be replayed and checked end-to-end in Godot; see
[CROSS_BACKEND_PARITY.md](CROSS_BACKEND_PARITY.md).

## Fresh-session procedure

Run from this repository's parent directory. The setup step reads an installed
copy of the game and creates a private, patched `sts2.dll` under the fork's
ignored `lib/` directory. It also writes a NuGet cache and normal .NET build
outputs inside the fork. It does not modify the installed game.

```bash
git clone --branch codex/current-sts2-compat \
  https://github.com/ericmarkmartin/sts2-cli.git
cd sts2-cli
git checkout 5e3e161

game_data="/mnt/c/Program Files (x86)/Steam/steamapps/common/Slay the Spire 2/data_sts2_windows_x86_64"
progress_save="/mnt/c/Users/<windows-user>/AppData/Roaming/SlayTheSpire2/steam/<steam-id>/modded/profile1/saves/progress.save"
cd ../sts2-sans-tet
./headless/run_sts2_cli_episode.sh \
  --cli-dir ../sts2-cli \
  --game-data-dir "$game_data" \
  --progress-save "$progress_save" \
  --setup \
  --seed HEADLESSBENCH \
  --policy-seed 0 \
  --max-actions 5000
```

`--setup` is only needed after a fresh clone or game-version change. Later
episodes use the same command without it.

`--progress-save` is required when the episode will be compared with a Godot
run using that profile. The wrapper extracts only the immutable run-generation
inputs: revealed epoch IDs, seen encounter IDs, and completed-run count. Those
values and their canonical SHA-256 are stored in the episode manifest. Without
this option the backend deliberately uses `UnlockState.all`, which is
deterministic but may generate different room queues from an active profile.

For permission-managed Codex sessions, review this script and permanently
approve only the stable prefix:

```text
["./headless/run_sts2_cli_episode.sh"]
```

The wrapper rejects tracked fork changes, unexpected fork revisions,
unexpected original/patched game DLL hashes, arbitrary executable or DLL
overrides, unsupported characters/modes, and unknown arguments. Updating the
pinned fork or game build therefore requires an explicit script review.

The command prints the allocated episode directory. Validate it offline:

```bash
./headless/run_sts2_cli_episode.sh \
  --validate-only headless/episodes/episode-NNNN
```

Run all offline headless tests or compare repeated seeded runs through the
same approved boundary:

```bash
./headless/run_sts2_cli_episode.sh --self-test
./headless/run_sts2_cli_episode.sh \
  --compare headless/episodes/episode-0004 \
            headless/episodes/episode-0005
```

Use `--observation-mode human` for agent evaluation. This exposes the members
of combat draw/discard/exhaust piles but hides draw order. Use
`--observation-mode authoritative` only for deterministic debugging or
privileged training experiments; it additionally preserves engine pile order.
Every decision carries schema `sts2-cli.observation.v1` and a canonical
SHA-256 observation checksum.

The runner records the fork revision, protocol version, standalone DLL hash,
original game DLL hash, patched runtime DLL hash, observation policy, profile
snapshot/fingerprint, seed, actions, results, terminal outcome, and binary
episode grade in `manifest.json`.

Replay and compare the complete episode in Godot:

```bash
./headless/run_episode.sh \
  --replay-episode headless/episodes/episode-NNNN \
  --progress-save "$progress_save"
```

This exits zero only after consuming every source action and matching the
terminal state. Inspect the reported `headless/parity-runs/parity-NNNN/`
directory for translated actions, states, Godot log, and detailed checkpoints.

## Copy-paste prompt for a fresh Codex session

```text
Read headless/STS2_CLI_BACKEND.md completely. Verify that the sts2-cli checkout
is exactly commit 5e3e161 (or report why a newer pinned commit is required).
Locate the active modded profile's saves/progress.save and pass it with
--progress-save so room-generation provenance matches Godot.
Run one full Ironclad episode in human observation mode with seed
HEADLESSBENCH, preserve the allocated episode directory, validate it with
the wrapper's --validate-only mode, then replay it through Godot with
./headless/run_episode.sh --replay-episode and the same --progress-save.
Require a complete parity match and
report the terminal grade, act/floor, action counts, elapsed time, profile
fingerprint, every recorded version/hash, and parity report path. Do not modify
the installed Steam game. Do not claim that an MP4 or MCR exists unless you
actually produced and validated it.
```

## Limitations

- This is not a redistributable game replacement. Setup requires assemblies
  from a locally installed, licensed game copy.
- Runtime does not contact Steam or launch the Steam client, but this is an
  engineering distinction rather than a statement about the game's license or
  ownership requirements.
- The backend patches a private copy of `sts2.dll` to remove two asynchronous
  waits and uses managed Godot stubs. Provenance must therefore pin both the
  original and patched DLL hashes.
- One 124-action, four-combat full run has matched Godot end-to-end. This is a
  strong integration proof, not exhaustive coverage across every card, event,
  relic, character, and act transition.
- The built-in `CombatReplayWriter` is not currently active on this standalone
  path. The episode JSONL trace now drives the Godot semantic replay adapter,
  but it is not itself an `.mcr` and cannot be passed directly to the game's
  native replay player.
- Post-hoc whole-episode MP4 capture still needs a rendered launch/capture mode
  around the validated action replay. Do not confuse semantic parity with an
  already-produced video artifact.
