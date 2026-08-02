# STS2 headless host

This directory contains the standalone .NET 9 compatibility probe described by
Phase A of `HEADLESS_PLAN.md`. It does not redistribute game files; point it at
the data directory of an installed copy of Slay the Spire 2.

## Build and probe

Enter the repository development shell first:

```bash
nix develop
```

On Windows:

```powershell
dotnet build
dotnet run -- probe --game-data-dir "D:\SteamLibrary\steamapps\common\Slay the Spire 2\data_sts2_windows_x86_64"
```

From WSL with a Windows .NET SDK:

```bash
project="$(wslpath -w "$PWD/headless")"
game_data='C:\Program Files (x86)\Steam\steamapps\common\Slay the Spire 2\data_sts2_windows_x86_64'
dotnet.exe run --project "$project" -- probe --game-data-dir "$game_data"
```

The probe writes newline-delimited JSON milestones to stdout and diagnostics to
stderr. Exit code 0 means `RunManager` was constructed; exit code 2 means the
assembly and type loaded but construction failed.

## Persistent stdio simulator

The standalone process now supports `health`, `reset`, `observe`, validated
`step` actions (`play_card` and `end_turn`), and `shutdown`. Reset can be called
repeatedly without restarting the process. See
[STDIO_PROTOCOL.md](STDIO_PROTOCOL.md) for the request/response contract and
current scope.

## Standalone full runs

Our pinned `sts2-cli` fork can already drive map, event, combat, reward,
rest-site, shop, and terminal states without Godot. The adapter in this
repository records its native, versioned observations in the same episode
layout used by the Godot-headless runner:

```bash
./headless/run_sts2_cli_episode.sh --cli-dir ../sts2-cli \
  --game-data-dir "<game>/data_sts2_windows_x86_64" \
  --progress-save "<active-modded-profile>/saves/progress.save"
```

See [STS2_CLI_BACKEND.md](STS2_CLI_BACKEND.md) for the pinned revision,
fresh-session setup, information-policy distinction, provenance fields, and
current replay limitations. Replay the resulting episode through Godot with:

```bash
./headless/run_episode.sh \
  --replay-episode headless/episodes/episode-NNNN
```

The replay uses the episode's recorded profile snapshot, character, ascension,
and seed; it does not require the original `progress.save`. This external
backend is now the practical full-run standalone baseline. Profile-backed and
all-unlocks episodes have matched Godot end-to-end; see
[CROSS_BACKEND_PARITY.md](CROSS_BACKEND_PARITY.md). The smaller host
implemented in this directory remains useful for testing minimal service
initialization and for measuring how much can eventually be brought in-tree.

Render the entire episode, including non-combat screens, to a muted MP4:

```bash
./headless/render_full_episode.sh headless/episodes/episode-NNNN
```

This fails closed on runtime hash drift, semantic divergence, profile writes,
wrong video dimensions/codecs, or an audio stream. See
[FULL_EPISODE_RENDER.md](FULL_EPISODE_RENDER.md) for outputs and the
fresh-session procedure.

## Phase A findings

Tested on 2026-07-26 against the installed Windows game assemblies from a Linux
.NET 9.0.316 process:

- `sts2.dll` loaded successfully.
- Its managed dependencies resolved from the game data directory:
  `GodotSharp.dll`, `Steamworks.NET.dll`, and `SmartFormat.dll`.
- All types needed for the probe loaded; there was no
  `ReflectionTypeLoadException`.
- `MegaCrit.Sts2.Core.Runs.RunManager` was found. It derives directly from
  `System.Object`, has a parameterless constructor, and constructed
  successfully.
- Construction did not trigger a Steam handshake or a Godot native-library
  error.

This clears Phase A's construction gate, but it does **not** yet establish that
run startup or combat can proceed without Godot's scene tree and native runtime.
Those are Phase B gates.

## Standalone findings and current boundary

The original plan assumes a `RunManager.StartRun(...)` entrypoint. The shipped
assembly has no such API. The intended pure-logic test seam is:

1. `ModelDb.Init()`
2. `ModelIdSerializationCache.Init()`
3. `ModelDb.InitIds()`
4. `RunState.CreateForTest(...)`
5. `RunManager.SetUpTest(...)` (or `SetUpNewSingleplayer(...)`)
6. `RunManager.Launch()`

The `phase-b-startup` command implements this experiment. It also marks
`ModManager` as skipped because `ModelDb.Init()` otherwise refuses to enumerate
models until mod initialization has completed.

The original cache initializer terminates in native Godot interop:
`ModelIdSerializationCache.Init()` uses `Godot.Mathf` and logs through
`MegaCrit.Sts2.Core.Logging.Log`; the logger initializes `Godot.OS`, whose
managed wrapper calls callbacks that only the engine installs.

The standalone host now mirrors that initializer with managed math, the exact
runtime `System.IO.Hashing.XxHash32`, and reflection over the game's private
cache collections. It also turns on the game's test mode and installs the
minimal in-memory progress graph needed by the default test player. Run:

```bash
dotnet run --project headless -- phase-b-startup \
  --game-data-dir "<game>/data_sts2_windows_x86_64"
```

This now exits zero after `RunState.CreateForTest(...)`. On game `v0.107.1` it
reports 1,624 model types, 20 categories, 1,622 unique entries, 57 epochs, and
cache hash `3954186980`, exactly matching the rendered build.

`phase-b-manager` continues into `RunManager.SetUpTest(...)` with a host-owned
no-op singleplayer `INetGameService` and now exits zero. The host selects the
game logger's console backend before its static initializer can query
`Godot.OS`; the real shared action, checksum, synchronization, and replay
services are retained.

`phase-c-combat` goes further: it creates a normal Ironclad starter deck,
launches the canonical `RunManager.Instance`, enters a deterministic encounter,
draws the opening hand, generates the normal checksum, and reaches player play
phase without starting Godot:

```bash
dotnet run --project headless -- phase-c-combat \
  --game-data-dir "<game>/data_sts2_windows_x86_64"
```

The action-cycle gate also passes:

```bash
dotnet run --project headless -- phase-c-action-cycle \
  --game-data-dir "<game>/data_sts2_windows_x86_64"
```

It plays a legal targeted card through the real synchronized action queue,
ends the turn, executes the enemy turn, and asserts the next player-ready
state. The initial authoritative state and legal-action schema is now
available:

```bash
dotnet run --project headless -- phase-d-observation \
  --game-data-dir "<game>/data_sts2_windows_x86_64"
```

It emits `sts2.standalone.combat.v1`; see
[OBSERVATION_SCHEMA.md](OBSERVATION_SCHEMA.md). The next milestone is accepting
these action identities through the stdio protocol and recording pre/post
observations as an episode. See
[STANDALONE_STATUS.md](STANDALONE_STATUS.md) and
[SHARED_SERVICE_INVENTORY.md](SHARED_SERVICE_INVENTORY.md).

The Godot-headless path remains the end-to-end reference and replay renderer.
The standalone path is now viable enough to pursue observation and action
serialization in parallel with the reference backend.

## Working Godot-headless reference path

For a fresh-session, start-to-finish procedure—including mod verification,
replay-path discovery, artifact checks, failure recovery, and a copy-paste
Codex prompt—follow [END_TO_END_REPLAY.md](END_TO_END_REPLAY.md).

The companion mod in `../godot_bootstrap/` supplies the release build's missing
`IBootstrapSettings` implementation. It can start either a deterministic fixed
combat or a normal act-entry run under
`--headless --audio-driver Dummy --bootstrap`. Run a full episode:

```bash
nix develop -c python benchmark_headless_episode.py \
  --full-run --seed HEADLESSBENCH --policy-seed 0 --max-actions 5000 \
  --mcr-source "<active-modded-profile>/replays/latest.mcr"
```

The runner allocates `headless/episodes/episode-NNNN/`, rejects a pre-existing
listener on port 15526, archives one `.mcr` per combat, records all actions and
states, writes version/build hashes into the manifest, and terminates the exact
Windows game process that it launched.

For a stable command boundary, invoke the same full-run workflow through:

```bash
./headless/run_episode.sh --mcr-source "<active-profile>/replays/latest.mcr"
```

Validate an existing episode without launching the game:

```bash
nix develop "path:$PWD" -c python headless/validate_episode.py \
  headless/episodes/episode-0001
```

Render its archived combat replays after simulation:

```bash
./headless/render_episode_replays.sh headless/episodes/episode-0001
```

The companion mod adds two headless lifecycle actions to the existing
singleplayer bridge:

```json
{"action":"reset","seed":"HEADLESSBENCH"}
{"action":"reset_status"}
```

`reset` returns a generation ID immediately. Poll `reset_status` until
`completed_reset_id` reaches it, then fetch state and require the player play
phase before acting.
