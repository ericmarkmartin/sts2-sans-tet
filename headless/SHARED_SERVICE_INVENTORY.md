# Standalone shared-service inventory

Validated against Slay the Spire 2 `v0.107.1` / release `59260271`.

The standalone host keeps `RunManager.InitializeShared` intact. Its purpose is
not to construct the smallest object graph that happens to run; it is to retain
the authoritative mechanics, determinism, provenance, and legal-action context
an agent needs. Engine-only presentation is isolated at narrower boundaries.

## Retained game services

| Service | Why it stays |
| --- | --- |
| `ChecksumTracker` | Detects state divergence and records deterministic checkpoints |
| `ActionQueueSet` / `ActionExecutor` | Own the canonical action ordering and execution lifecycle |
| `ActionQueueSynchronizer` | Maintains action/combat phase agreement |
| `PlayerChoiceSynchronizer` | Preserves paused choices and legal continuation semantics |
| `CombatStateSynchronizer` | Preserves combat-entry state agreement |
| `MapSelectionSynchronizer` | Preserves map-choice state |
| `ActChangeSynchronizer` | Preserves act transitions |
| `EventSynchronizer` | Preserves event choices and outcomes |
| `RewardSynchronizer` / `RewardsSetSynchronizer` | Preserve reward generation and selection |
| `RestSiteSynchronizer` | Preserves rest-site choices |
| `TreasureRoomRelicSynchronizer` | Preserves treasure-room relic choices |
| `OneOffSynchronizer` | Preserves miscellaneous synchronized decisions |
| `RunLocationTargetedMessageBuffer` | Preserves location-scoped ordering |
| `CombatReplayWriter` | Keeps the native provenance implementation available; `TestMode` currently leaves `IsEnabled` false |
| `AscensionManager` | Preserves ascension rule application |

These services are constructed by the game and are not replaced by host-owned
implementations. Construction alone does not imply every service is active:
the current standalone probe relies on `TestMode`, which disables native `.mcr`
recording. Enabling that safely or recording an equivalent authoritative action
stream remains a separate milestone.

## Presentation/input services

`FlavorSynchronizer`, `PeerInputSynchronizer`, and `HoveredModelTracker` carry
multiplayer pings, pointer input, and hover presentation. They remain in the
shared graph for compatibility, but they are not authoritative sources for
singleplayer strategy. A future standalone protocol should derive observations
from run/combat models and synchronizer choice contexts, not from these UI
trackers.

## Host-owned compatibility seams

| Seam | Scope | Fidelity assessment |
| --- | --- | --- |
| Console-logger selection | Skips `Logger.GetIsRunningFromGodotEditor()` and returns `false` | Logging backend only |
| Structured host logging | Suppresses engine-adjacent `Log.Info` and replaces localized action/creature descriptions | Diagnostics only; JSON milestones retain observable progress |
| Monotonic clock | Replaces `Godot.Time.GetTicksMsec()` with `Environment.TickCount64` | Preserves history ordering without engine time |
| In-memory save graph | Supplies default progress needed during player construction | Persistence is absent; run mechanics use the resulting immutable run unlock state |
| FTUE disabled | Sets `ProgressState.EnableFtues = false` | Tutorial overlays only |
| No-op `INetGameService` | Reports connected singleplayer and completes transport tasks immediately | Appropriate for singleplayer; multiplayer is out of scope |
| Test/noninteractive mode | Uses the game's own branches to skip scene nodes, audio timing, and visual waits | Mechanics and hooks still execute |
| Checksum opt-in | Re-enables `ChecksumTracker.IsEnabled` for the action-cycle probe after `TestMode` disables it | Restores canonical full-state checksums |
| Managed model-cache math | Replaces three `Godot.Mathf` calls with equivalent managed math | Cache counts and hash match the rendered game exactly |

## Observation contract

Maximal agent information does not mean retaining scene nodes. The standalone
observation layer should expose:

- complete `RunState` and `CombatState` values relevant to decisions;
- player HP, block, energy, powers, relics, potions, piles, and card modifiers;
- enemies, intents, powers, targetability, and hidden-information rules;
- current room, map, event, reward, shop, rest, and player-choice contexts;
- RNG/checksum/provenance identifiers that are safe to expose for the intended
  evaluation regime; and
- legal actions generated from authoritative phase and choice state.

Presentation-only data such as animation progress, hover state, particle
effects, and audio need not enter the policy observation. If an evaluation
intentionally restricts information available to a human player, that
restriction belongs in the observation serializer, not in the simulator's
internal service graph.
