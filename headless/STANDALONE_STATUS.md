# Standalone DLL host status

Validated against Slay the Spire 2 `v0.107.1` / release `59260271`.

## Passing managed-only boundary

`phase-b-startup` now completes without starting Godot, Steam, or the Windows
game process. It:

1. loads `sts2.dll` and its managed dependencies;
2. marks mod enumeration skipped;
3. enables the game's test mode;
4. constructs all built-in models;
5. mirrors the no-mod branch of `ModelIdSerializationCache.Init()` without
   `Godot.Mathf` or the Godot-backed logger;
6. assigns canonical model IDs;
7. installs the minimal in-memory progress graph read by `Player`; and
8. creates a deterministic `RunState` with seed `HEADLESSBENCH`.

Observed cache result:

```text
model types: 1624
categories: 20
entries: 1622
epochs: 57
hash: 3954186980
```

The counts and hash exactly match the rendered game. Matching the hash requires
using `List<T>.Sort` with the game's simple-name comparer: two model types share
a simple name, and replacing the game's unstable sort with stable LINQ ordering
changes the serialized cache hash.

## Host-owned seams

| Game dependency | Standalone treatment |
| --- | --- |
| `ModManager` initialization | Marked `Skipped`; no mods loaded |
| `Godot.Mathf.CeilToInt` | Managed `Math.Ceiling(Math.Log2(...))` |
| cache `Log.Info` | Omitted; milestone emitted as JSON |
| `System.IO.Hashing.XxHash32` | Loaded from the game data directory and invoked exactly |
| `SaveManager` | Uninitialized narrow graph containing default `ProgressState` |
| `INetGameService` | `DispatchProxy` no-op service for the manager experiment |

These are probe-only compatibility seams. They fail on missing private fields
or methods rather than silently accepting a changed game assembly.

## Current failing boundary

`phase-b-manager` continues after `RunState` construction and calls
`RunManager.SetUpTest(...)`. It creates the standalone network proxy, then
terminates with SIGSEGV inside the shared run-service initialization path.
Because native Godot callbacks are uninstalled, this is not a catchable managed
exception.

The next task is to split or reproduce `RunManager.InitializeShared` one
collaborator at a time and identify the first constructor that invokes Godot.
Likely candidates are the synchronization/action services constructed before
`ActionExecutor.Pause()`. Do not start protocol or Gym work until manager setup
and at least one logic action complete without native calls.

## Commands

Safe successful boundary:

```bash
dotnet run --project headless -- phase-b-startup \
  --game-data-dir "<game>/data_sts2_windows_x86_64"
```

Unsafe crash-localization boundary:

```bash
dotnet run --project headless -- phase-b-manager \
  --game-data-dir "<game>/data_sts2_windows_x86_64"
```
