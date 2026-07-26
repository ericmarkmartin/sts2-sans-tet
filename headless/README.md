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

## Minimal stdio smoke test

The protocol shell currently exposes only `health` and `shutdown`; gameplay
commands must not be added until the Phase A construction result establishes
which runtime services need hosting.

```text
{"cmd":"health"}
{"cmd":"shutdown"}
```

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

## Phase B findings and current blocker

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

The experiment currently reaches model initialization, then terminates in
native Godot interop. `ModelIdSerializationCache.Init()` logs through
`MegaCrit.Sts2.Core.Logging.Log`; the logger initializes `Godot.OS`, whose
managed wrapper calls native callbacks that only the Godot engine installs.
This is a process-level access violation/SIGSEGV, not a catchable .NET
exception. It reproduces both:

- on Linux while resolving the installed Windows `GodotSharp.dll`; and
- in a self-contained Windows .NET 9 host with the matching Windows assembly.

Therefore resolving the real `GodotSharp.dll` is sufficient for type loading
but **not** for executing arbitrary game methods outside Godot.

### Recommended next decision

Before implementing combat, serialization, or Python plumbing, choose and
benchmark one of these:

1. Build a minimal replacement `GodotSharp` stub assembly. Start with the exact
   surface reached by model bootstrap (`OS`, `StringName`, `Mathf`, and logging
   dependencies), then grow it from observed failures. This preserves the
   standalone-process goal but the total stubbing surface is still unknown.
2. Run the actual game executable with Godot's `--headless` display driver and
   a thin in-engine bridge. This is less pure, but validates achievable
   throughput and gameplay automation before paying the stubbing cost.

Do not proceed to protocol-parity work until one path can initialize `ModelDb`
and construct a `RunState`; otherwise Phases C–E would only produce plumbing
around a backend that cannot reset.

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
