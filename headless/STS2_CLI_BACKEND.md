# Standalone full-run backend (`sts2-cli`)

This is the shortest path from a fresh Codex session to a recorded full run
without launching Godot or Steam. It uses our compatibility branch of
[`ericmarkmartin/sts2-cli`](https://github.com/ericmarkmartin/sts2-cli),
pinned here to commit `f4c83d0`.

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
Rendering therefore remains a separate parity/replay project; see
[Limitations](#limitations).

## Fresh-session procedure

Run from this repository's parent directory. The setup step reads an installed
copy of the game and creates a private, patched `sts2.dll` under the fork's
ignored `lib/` directory. It also writes a NuGet cache and normal .NET build
outputs inside the fork. It does not modify the installed game.

```bash
git clone --branch codex/current-sts2-compat \
  https://github.com/ericmarkmartin/sts2-cli.git
cd sts2-cli
git checkout f4c83d0

game_data="/mnt/c/Program Files (x86)/Steam/steamapps/common/Slay the Spire 2/data_sts2_windows_x86_64"
cd ../sts2-sans-tet
./headless/run_sts2_cli_episode.sh \
  --cli-dir ../sts2-cli \
  --game-data-dir "$game_data" \
  --setup \
  --seed HEADLESSBENCH \
  --policy-seed 0 \
  --max-actions 5000
```

`--setup` is only needed after a fresh clone or game-version change. Later
episodes use the same command without it.

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
original game DLL hash, patched runtime DLL hash, observation policy, seed,
actions, results, terminal outcome, and binary episode grade in
`manifest.json`.

## Copy-paste prompt for a fresh Codex session

```text
Read headless/STS2_CLI_BACKEND.md completely. Verify that the sts2-cli checkout
is exactly commit f4c83d0 (or report why a newer pinned commit is required).
Run one full Ironclad episode in human observation mode with seed
HEADLESSBENCH, preserve the allocated episode directory, validate it with
the wrapper's --validate-only mode, and report the terminal grade, act/floor,
action count, elapsed time, and every recorded version/hash. Do not modify the
installed Steam game. Do not claim that an MP4 or MCR exists unless you
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
- The fork has broad run coverage and a passing test suite, but it is not yet
  proven behaviorally identical to the rendered game across every card, event,
  relic, and act transition.
- The built-in `CombatReplayWriter` is not currently active on this standalone
  path. An episode JSONL trace can drive a future rendered replay adapter, but
  it is not itself an `.mcr` and cannot yet be passed directly to the game's
  replay player.
- Post-hoc video requires either deterministic action replay in a pinned
  rendered build or a purpose-built trace renderer. Cross-backend observation
  checksum comparison should be the acceptance gate before treating that
  video as a faithful replay.
