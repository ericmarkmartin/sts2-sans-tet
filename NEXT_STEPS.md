# Next Steps

## Immediate: Multi-Episode Looping

Currently the game quits after each episode. For training we need continuous runs.

### AutoSlayer lifecycle

`AutoSlayer.Start()` kicks off `RunAsync()` as a fire-and-forget task. `RunAsync()` calls `PlayRunAsync()`, and its `finally` block sets `IsActive = false` and calls `QuitGame()`. The flow is:

```
Start() → RunAsync() → PlayRunAsync() → [run plays out] → finally { QuitGame() }
```

### Approaches tried

1. **Patching `RunAsync` to loop** — called `PlayRunAsync` via reflection after each run. Problem: `RunAsync`'s `finally` block does cleanup (`IsActive = false`, dispose card selector, close log), so calling `PlayRunAsync` again after that leaves broken state.

2. **Patching `QuitGame` as a no-op + wrapper around `Start`** — tried calling `Start` again from a wrapper. Problem: `Start` would re-enter the patch, creating recursion.

### Suggested approach

Patch `RunAsync` directly (it's private, but Harmony can patch by name). Replace it with a version that:
1. Keeps the setup from `PlayRunAsync` (seed, FastMode, character unlocks, RNG, card selector)
2. Loops: after `PlayRunAsync` completes (death/victory), send `episode_end`, wait for `reset_ack`, re-setup, and call `PlayMainMenuAsync` + `PlayRunAsync` again
3. Handles cleanup properly between episodes (re-initialize `_random`, `_watchdog`, `_cardSelectorScope`)
4. Only calls `QuitGame` when the Python agent disconnects

Key methods to call between episodes (from `AutoSlayer`, accessed via reflection):
- `PlayMainMenuAsync(ct)` — navigates menus, picks character, starts run
- `PlayRunAsync(seed, ct)` — plays the full run

The `_cardSelectorScope`, `_random`, and `_watchdog` fields need to be re-initialized between runs. All are private fields on the `AutoSlayer` instance.

### Simpler alternative

Have Python relaunch the game process for each episode. Slower (~30s startup per episode) but avoids all lifecycle issues. Good enough for initial experiments.

## Phase A Improvements

- **Richer observations**: draw/discard pile composition, relic effects, orb state
- **Better action validation**: return feedback to agent on invalid actions instead of silently ending turn
- **Parallel instances**: multiple game instances on different ports
- **RL framework integration**: SB3, cleanrl, or custom PPO

## Phase B: Headless Harness

Load `sts2.dll` in a standalone .NET process without Godot for maximum throughput.

Key enablers already in game code:
- `NonInteractiveMode.IsActive` — skips animations and frame waits
- `TestMode.IsOn` — disables visual creation
- `FastMode = Instant` — skips all `Cmd.Wait()` timing
- Null-safe Godot calls — combat code uses `?.` on all node references

Would need to:
- Stub out Godot types (`Vector2`, `Texture2D`, `SceneTree`, `Engine.GetMainLoop()`)
- Drive via `RunManager` + `CombatManager` + `ActionQueueSet` directly
- Mock or skip `Cmd.Wait()` (already skipped in NonInteractiveMode)

Target: thousands of games/sec vs ~1 game/min with mod approach.

## Phase C: Training

- Curriculum learning: start with single-act runs, progress to full runs
- Reward shaping: per-combat rewards, deck quality metrics
- Action masking: leverage `valid_actions` to constrain policy output
- Observation encoding: fixed-size tensor representations for neural network input
