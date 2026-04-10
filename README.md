# sts2-sans-tet

RL training harness for Slay the Spire 2.

## What This Is

A system for training AI agents to play Slay the Spire 2. It uses [STS2MCP](https://github.com/Gennadiyev/STS2MCP) (a mod that exposes game state and actions via REST API) as the game interface, with our [fork](https://github.com/ericmarkmartin/STS2MCP) adding episode lifecycle automation.

The game runs normally while a Python agent polls the REST API for game state and posts actions. A protocol layer (planned) will abstract over two backends — Godot (via STS2MCP) for eval/demo, and headless (direct sts2.dll) for high-throughput training.

## Status

**Multi-episode loop working.** A random agent can:
- Navigate menus (singleplayer → standard → character select → confirm)
- Abandon existing runs, dismiss modals
- Handle timeline/unlock screens
- Play through all in-run states: combat, map, events, rewards, card select, shops, rest sites
- Handle game over (continue → main menu → start new run)
- Loop continuously across episodes

The random agent dies fast (floor 2-6), so later-game states (bosses, act transitions) are under-tested.

## Quick Start

### Prerequisites
- Slay the Spire 2 (Steam, Windows)
- .NET 9 SDK
- Python 3.11+ with uv
- WSL2 (Python runs on WSL, game runs on Windows)
- Mods enabled in STS2 settings (launch game, accept the mod consent dialog)

### Setup
```bash
# Build and install STS2MCP (our fork)
cd ~/Development/STS2MCP
dotnet build -p:STS2GameDataDir="/mnt/c/Program Files (x86)/Steam/steamapps/common/Slay the Spire 2/data_sts2_windows_x86_64"
mkdir -p "/mnt/c/Program Files (x86)/Steam/steamapps/common/Slay the Spire 2/mods/STS2_MCP"
cp mod_manifest.json "/mnt/c/Program Files (x86)/Steam/steamapps/common/Slay the Spire 2/mods/STS2_MCP/manifest.json"
cp bin/Debug/net9.0/STS2_MCP.dll "/mnt/c/Program Files (x86)/Steam/steamapps/common/Slay the Spire 2/mods/STS2_MCP/"

# Install Python deps
cd ~/Development/sts2-sans-tet
uv sync
```

### Run
```bash
# Launch game
cmd.exe /c 'start steam://run/2868840'

# Start random agent (handles menu navigation automatically)
uv run python test_sts2mcp_random.py
```

## Architecture

See [NEXT_STEPS.md](NEXT_STEPS.md) for the full architecture plan.

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

## Key Files

- `test_sts2mcp_random.py` — Random agent smoke test with full episode lifecycle
- `sts2_rl/` — Python environment (being rewritten for protocol layer)
- `mod/` — Old custom Harmony mod (kept as reference, replaced by STS2MCP)
- `decompiled/` — ILSpy-decompiled STS2 source (3,304 C# files, not checked in)
- `NEXT_STEPS.md` — Roadmap and implementation notes

## Roadmap

1. **Protocol layer** — Python abstraction matching STS2MCP's API, exposed as both Python API and MCP server
2. **Better agent** — Needs to survive longer to exercise late-game states
3. **Headless backend** — Load sts2.dll without Godot for thousands of games/sec
4. **RL training** — Curriculum learning, reward shaping, action masking
