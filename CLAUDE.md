# STS2 RL Training Harness

## Building

```bash
cd mod && dotnet build
```

Requires .NET 9 SDK. References game DLLs from Steam install at
`/mnt/c/Program Files (x86)/Steam/steamapps/common/Slay the Spire 2/data_sts2_windows_x86_64/`.

## Installing the Mod

```bash
cp mod/manifest.json mod/bin/Debug/net9.0/rl_bridge.dll \
  "/mnt/c/Program Files (x86)/Steam/steamapps/common/Slay the Spire 2/mods/rl_bridge/"
```

## Python

```bash
uv sync
```

## Running

1. Start Python agent: `uv run python test_random_agent.py`
2. Launch game via Steam with `--autoslay --seed <seed>` (set in Steam launch options, or from WSL: `cmd.exe /c 'start steam://run/2868840//--autoslay --seed test123'`)

## Key Files

- See `README.md` for architecture and how everything works
- See `NEXT_STEPS.md` for roadmap and implementation notes
