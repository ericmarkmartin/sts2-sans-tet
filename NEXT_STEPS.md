# Next Steps

## Current direction (2026-07-30)

The original roadmap below predates the Godot-headless benchmarks, the in-tree
standalone experiments, and the `sts2-cli` evaluation. The working architecture
is now:

```text
agent / training loop
        |
episode + observation contract
   _____|_____
  |           |
sts2-cli      Godot headless + STS2MCP
standalone    reference/replay renderer
```

- Use the pinned `ericmarkmartin/sts2-cli@f4c83d0` fork as the practical
  standalone full-run backend. It does not launch Godot or Steam, but still
  requires assemblies from an installed game and runs a privately patched
  copy of `sts2.dll`.
- Use the real game under Godot headless as the semantic reference, built-in
  `.mcr` source, and MP4 renderer.
- Preserve backend-native observations and make their information policy
  explicit. Human evaluation hides private draw order; authoritative debugging
  may expose it.
- Keep the smaller in-tree standalone host as a compatibility/performance
  experiment. Do not duplicate the fork's broad run implementation unless a
  benchmark or maintainability result justifies it.
- Do not promise thousands of games per second. The first complete standalone
  episodes execute roughly 32–43 external decisions per second including
  simulator startup; throughput needs controlled multi-episode and
  multi-process measurement.

Immediate work:

1. Checkpoint and push the tested standalone episode adapter.
2. Add cross-backend fixtures for representative combat and non-combat
   decisions, including legal actions and visible-information policy.
3. Replay a standalone episode's external action trace in a pinned rendered
   build and compare observation/checksum checkpoints.
4. Only after parity is measured, build the JSONL-to-rendered-video path for
   out-of-combat transitions.
5. Improve the policy and later-state coverage independently from backend
   correctness.

The remaining sections record the original architecture rationale. Treat their
uncompleted phase ordering as historical, not as the active execution plan;
the maintained implementation plan is [HEADLESS_PLAN.md](HEADLESS_PLAN.md).

## Architecture

```
┌─ RL training loop (Python API)
│
Protocol Layer ──┤
│                └─ LLM agent (MCP server)
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

The protocol layer is exposed two ways:
- **Python API** for RL training loops (gymnasium env, direct calls)
- **MCP server** for LLM agents (Claude Desktop/Code, other MCP clients)

Both interfaces are backend-agnostic — an LLM can play against either Godot or headless. This makes STS2MCP's own MCP server redundant once our protocol layer is in place, since theirs is pinned to the Godot backend only.

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

## Original Phase 2: Headless Backend

**Original goal:** Explore a substantially faster backend for training.

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
