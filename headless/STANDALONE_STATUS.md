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
8. creates a deterministic Ironclad `RunState` with seed `HEADLESSBENCH`;
9. initializes and launches the canonical `RunManager.Instance`; and
10. enters a Fuzzy Wurm/Crawler combat through the normal room lifecycle,
    executes start-of-combat hooks, draws five cards, generates a checksum, and
    reaches player play phase; and
11. submits a legal Strike and end turn through the canonical synchronized
    action queue, executes the enemy turn, and reaches turn two.

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
| logger editor probe | Harmony prefix selects the console logger without calling `Godot.OS` |
| game `Log.Info` | Suppressed; the host emits structured JSON milestones |
| localized action/creature log descriptions | Replaced with ID-neutral descriptions |
| `Godot.Time.GetTicksMsec` | Managed monotonic milliseconds for history timestamps |
| `System.IO.Hashing.XxHash32` | Loaded from the game data directory and invoked exactly |
| `SaveManager` | Uninitialized narrow graph containing default `ProgressState`; FTUE presentation disabled |
| `INetGameService` | `DispatchProxy` no-op singleplayer service |
| visual waits and nodes | Suppressed by the game's `TestMode` / `NonInteractiveMode` branches |

These compatibility seams fail on missing private fields or methods rather than
silently accepting a changed game assembly. FTUE suppression changes tutorial
overlays only. All mechanics-bearing shared services remain the game's real
implementations; see `SHARED_SERVICE_INVENTORY.md`.

## Current boundary

`phase-b-manager` and `phase-c-combat` both exit zero. The combat command uses
the canonical `RunManager.Instance`; this is required because combat and command
code resolve that singleton internally. It explicitly constructs an Ironclad
player with the all-unlocked test state because `RunState.CreateForTest()` uses
the deckless `Deprived` character when its player argument is omitted.

The complete logic-action gate now passes. `phase-c-action-cycle` observes a
deterministic Strike reducing enemy HP from 56 to 50, the enemy reducing player
HP from 80 to 76, turn advancing from 1 to 2, energy returning to 3, a new
five-card hand, and checksums changing from `3932430620` to `1034061027`.

The next gate is authoritative state and legal-action serialization following
the models and active choice contexts, not scene nodes. The first combat schema,
`sts2.standalone.combat.v1`, now exposes an explicitly
`omniscient_authoritative` observation with numeric card variables, all piles,
enemy intent damage, and legal card/target pairs. The next gate is accepting
those identities through stdio and recording pre/post observations. Native `.mcr`
writing is not yet active because the game disables `CombatReplayWriter` in
`TestMode`; the Godot-headless path remains the replay reference.

## Commands

Successful startup and manager boundaries:

```bash
dotnet run --project headless -- phase-b-startup \
  --game-data-dir "<game>/data_sts2_windows_x86_64"
dotnet run --project headless -- phase-b-manager \
  --game-data-dir "<game>/data_sts2_windows_x86_64"
dotnet run --project headless -- phase-c-combat \
  --game-data-dir "<game>/data_sts2_windows_x86_64"
dotnet run --project headless -- phase-c-action-cycle \
  --game-data-dir "<game>/data_sts2_windows_x86_64"
dotnet run --project headless -- phase-d-observation \
  --game-data-dir "<game>/data_sts2_windows_x86_64"
```

Set `STS2_STANDALONE_TRACE=1` to install read-only Harmony prefixes that emit
managed method-boundary milestones. This is intended only to localize native
callback failures and does not skip the traced game methods.
