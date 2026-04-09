# sts2-sans-tet

RL training harness for Slay the Spire 2.

## What This Is

A system for training AI agents to play Slay the Spire 2 via reinforcement learning. It works by patching the game's built-in automated player (AutoSlay) to communicate with an external Python process over TCP, replacing random decisions with agent-driven ones.

The game runs normally (with fast animations), while a Python gymnasium environment receives structured observations (hand, enemies, intents, energy, etc.) and sends back actions (play card, end turn, use potion, pick card reward, navigate map).

## Status

**Phase A (current): Mod-based harness — working for single episodes.**

What works:
- Combat: full observation space (hand, enemies, intents, powers, energy, valid actions), card play with targeting, potions, end turn
- Card rewards: agent picks from offered cards or skips
- Map navigation: agent chooses which room to visit next
- Episode end: death/victory reported to Python with final stats
- Reward computation: floor progress, HP delta, combat/run outcomes

What doesn't work yet:
- Multi-episode looping (game quits after each run, must relaunch)
- Event decisions (patched but not well-tested)
- Rest site decisions (patched but not well-tested)
- Shop decisions (uses original random AutoSlay behavior)

## How It Works

### C# Mod (`mod/`)

A Harmony mod that loads into STS2 via the game's native mod system. It applies prefix patches to AutoSlay's decision handlers:

| Patch | What it replaces |
|-------|-----------------|
| `IsReleaseGamePatch` | Unlocks AutoSlay on release builds |
| `CombatPatch` | Card/target/potion selection + end turn |
| `MapPatch` | Path selection on the dungeon map |
| `CardRewardPatch` | Card pick after combat |
| `EventPatch` | Event option selection |
| `RestSitePatch` | Rest vs upgrade at campfires |
| `QuitGamePatch` | Sends episode_end before game exits |

### Python Environment (`sts2_rl/`)

A gymnasium-compatible environment that acts as a TCP server:

```python
from sts2_rl.env import STS2Env

env = STS2Env(port=19720)
obs, info = env.reset()
while not done:
    action = agent.predict(obs)
    obs, reward, terminated, truncated, info = env.step(action)
```

### IPC Protocol

Newline-delimited JSON over TCP on localhost:19720.

```
Game → Python:  {"type":"obs","decision_type":"combat","obs":{...},"run_context":{...}}
Python → Game:  {"type":"action","action_type":"play_card","card_index":2,"target_index":0}
Game → Python:  {"type":"episode_end","result":"death","floor_reached":3,"final_hp":0,...}
```

## Quick Start

### Prerequisites
- Slay the Spire 2 (Steam, Windows)
- .NET 9 SDK (for building the mod)
- Python 3.11+ with uv
- WSL2 (for running Python agent; game runs on Windows)
- Mods enabled in STS2 settings

### Setup
```bash
# Build and install the mod
cd mod && dotnet build
cp manifest.json bin/Debug/net9.0/rl_bridge.dll \
  "/mnt/c/Program Files (x86)/Steam/steamapps/common/Slay the Spire 2/mods/rl_bridge/"

# Install Python deps
uv sync
```

### Run
```bash
# Terminal 1: start agent
uv run python test_random_agent.py

# Terminal 2: launch game (or set Steam launch options to: --autoslay --seed test123)
cmd.exe /c 'start steam://run/2868840//--autoslay --seed test123'
```

## Roadmap

### Phase A improvements (mod-based)
- **Multi-episode looping**: patch AutoSlayer to restart runs instead of quitting, enabling continuous training without relaunching
- **Richer observations**: draw pile composition, discard pile contents, relic effects, orb state
- **Better action validation**: return invalid action feedback to agent instead of silently ending turn
- **Parallel instances**: run multiple game instances on different ports for faster data collection
- **Integration with RL frameworks**: SB3, cleanrl, or custom PPO

### Phase B: Headless harness
- Load `sts2.dll` in a standalone .NET process without Godot
- Drive game logic directly via `RunManager`, `CombatManager`, `ActionQueueSet`
- Stub out Godot dependencies (`Vector2`, `Texture2D`, timing)
- Target: thousands of games/sec vs ~1 game/min with the mod approach
- Key enablers already in game code: `NonInteractiveMode`, `TestMode`, null-safe Godot calls

### Phase C: Training
- Curriculum learning: start with single-act runs, progress to full runs
- Reward shaping: per-combat rewards, deck quality metrics
- Action masking: leverage `valid_actions` to constrain policy
- Observation encoding: fixed-size representations for neural network input
