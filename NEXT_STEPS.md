# Next Steps

## Architecture

```
Agent / Training Loop
        │
   Protocol Layer  (Python — our abstraction)
        │
   ┌────┴────┐
   │         │
 Godot     Headless
 Backend   Backend
   │         │
 STS2MCP   sts2.dll
 REST API  (direct .NET)
```

The protocol layer defines the contract: `get_state()`, `play_card()`, `end_turn()`, `choose_map_node()`, etc. It matches STS2MCP's JSON state format and action names as the canonical API shape. The Godot backend is a thin pass-through to STS2MCP's REST API. The headless backend calls into game logic directly.

Agent code never knows which backend it's talking to. Training uses headless for throughput, eval/demo uses Godot to watch it play.

If RL needs optimized tensor representations, that's handled in the training code (observation encoding), not the protocol.

## Phase 1: Fork STS2MCP + Episode Management

**Goal:** Continuous multi-episode training against a real Godot instance.

Fork [STS2MCP](https://github.com/Gennadiyev/STS2MCP) and add episode lifecycle endpoints:

- `POST /api/v1/start_run` — navigate menus, pick character/ascension, begin a run
- `POST /api/v1/restart` — handle game-over screen, return to menu, start new run
- `GET /api/v1/episode_status` — is run in progress, did player die, did player win

STS2MCP already has the `RunOnMainThread` queue for executing actions on the Godot thread, Instant Mode support, and comprehensive state/action coverage (37 actions, all game screens). Our current custom mod's observation builder and action handling become unnecessary.

**Deliver:**
- Forked STS2MCP with episode management
- Python protocol layer with Godot backend (wraps REST API)
- `STS2Env` gymnasium wrapper using the protocol layer
- Random-policy smoke test running continuous episodes

## Phase 2: Headless Backend

**Goal:** Thousands of games/sec for large-scale training.

Load `sts2.dll` in a standalone .NET process without Godot. Implement the same protocol contract as the Godot backend.

Key enablers already in game code:
- `NonInteractiveMode.IsActive` — skips animations and frame waits
- `TestMode.IsOn` — disables visual creation
- `FastMode = Instant` — skips all `Cmd.Wait()` timing
- Null-safe Godot calls — combat code uses `?.` on all node references

Would need to:
- Stub out Godot types (`Vector2`, `Texture2D`, `SceneTree`, `Engine.GetMainLoop()`)
- Drive via `RunManager` + `CombatManager` + `ActionQueueSet` directly
- Implement state serialization matching STS2MCP's JSON format
- Implement action execution matching STS2MCP's action names

The headless backend exposes the same Python protocol interface, so training code works unchanged.

## Phase 3: Training

- Curriculum learning: start with single-act runs, progress to full runs
- Reward shaping: per-combat rewards, deck quality metrics
- Action masking: leverage valid action lists from state to constrain policy output
- Observation encoding: fixed-size tensor representations for neural network input
- Integration with SB3, cleanrl, or custom PPO

## Current State (as of 2026-04-09)

We have a working proof-of-concept (custom Harmony mod + Python env) that demonstrates single-episode combat, card rewards, and map navigation via TCP. This will be replaced by the architecture above. The existing code is useful as reference for:
- How Harmony patching works with STS2 (`mod/src/Patches/`)
- What game APIs exist for state reading and action execution (`mod/src/ObservationBuilder.cs`, `mod/src/Patches/CombatPatch.cs`)
- The decompiled source structure (`decompiled/` — 3,304 C# files from ILSpy)
- API naming gotchas (see memory file `sts2_architecture.md`)
