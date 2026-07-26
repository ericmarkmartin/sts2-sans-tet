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
no-op `INetGameService`. It remains an intentionally unsafe diagnostic:
construction reaches native Godot while initializing shared run services and
currently exits with SIGSEGV. The next investigation is the constructor set in
`RunManager.InitializeShared`, not model loading or run-state construction.

### Recommended next decision

Before implementing combat, serialization, or Python plumbing, choose and
benchmark one of these:

1. Decompose `RunManager.InitializeShared` and replace only the first
   engine-bound collaborator with a host-owned implementation, as already done
   for model-cache initialization, saves, and networking. This preserves the
   standalone-process goal while keeping the stub surface evidence-driven.
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
