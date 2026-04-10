# STS2 RL Training Harness

## Building STS2MCP (game mod)

```bash
cd ~/Development/STS2MCP
dotnet build -p:STS2GameDataDir="/mnt/c/Program Files (x86)/Steam/steamapps/common/Slay the Spire 2/data_sts2_windows_x86_64"
```

## Installing STS2MCP

```bash
mkdir -p "/mnt/c/Program Files (x86)/Steam/steamapps/common/Slay the Spire 2/mods/STS2_MCP"
cp ~/Development/STS2MCP/mod_manifest.json \
  "/mnt/c/Program Files (x86)/Steam/steamapps/common/Slay the Spire 2/mods/STS2_MCP/manifest.json"
cp ~/Development/STS2MCP/bin/Debug/net9.0/STS2_MCP.dll \
  "/mnt/c/Program Files (x86)/Steam/steamapps/common/Slay the Spire 2/mods/STS2_MCP/"
```

## Python

```bash
uv sync
```

## Running

1. Launch game via Steam: `cmd.exe /c 'start steam://run/2868840'`
2. Start random agent: `uv run python test_sts2mcp_random.py`
   (agent handles menu navigation and starts runs automatically)

## Key Files

- See `README.md` for architecture and how everything works
- See `NEXT_STEPS.md` for roadmap and implementation notes
- STS2MCP fork: `~/Development/STS2MCP` (github.com/ericmarkmartin/STS2MCP)
- Decompiled game source: `decompiled/` (not checked in)
