# STS2 headless bootstrap mod

This mod activates the game's built-in `--bootstrap` path, whose settings
implementation is intentionally absent from release builds. It can start a
seeded Ironclad combat against `FuzzyWurmCrawlerWeak` without loading the main
menu or enter the normal seeded act lifecycle for full-run simulation.

When STS2MCP is loaded, the mod also adds guarded `reset` and `reset_status`
actions. They repeat the game's own cleanup/bootstrap sequence in-process and
report completion with reset generation IDs. Full-run mode also exposes the
narrow replay flush needed to archive a loss before shutdown.

When `STS2_REPLAY_PATH` names an archived `.mcr`, the mod replaces normal
bootstrap with the game's internal combat replay player and quits after a short
tail. `headless/render_combat_replay.ps1` uses this mode with Godot's movie
writer; FFmpeg can then transcode the resulting AVI to MP4. Current episode
replays do not contain checksum samples, so this playback is action-replayed
rather than checksum-validated.

Build:

```bash
dotnet build godot_bootstrap \
  -p:STS2GameDataDir="/mnt/c/Program Files (x86)/Steam/steamapps/common/Slay the Spire 2/data_sts2_windows_x86_64"
```

Install `manifest.json` as `manifest.json` and the output DLL as
`STS2_BOOTSTRAP.dll` in the game's `mods/STS2_BOOTSTRAP/` directory. Set
`STS2_BOOTSTRAP_SEED` to override the default `HEADLESSBENCH` seed.

See `headless/END_TO_END_REPLAY.md` and `headless/HANDOFF.md` for the validated
simulation and rendering workflows, limitations, and next work.
