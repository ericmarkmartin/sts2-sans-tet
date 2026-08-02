# STS2 headless bootstrap mod

This mod activates the game's built-in `--bootstrap` path, whose settings
implementation is intentionally absent from release builds. It can start a
seeded combat against `FuzzyWurmCrawlerWeak` without loading the main menu or
enter the normal seeded act lifecycle for full-run simulation.

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

Portable full-run initialization also accepts:

- `STS2_BOOTSTRAP_CHARACTER`: `Ironclad`, `Silent`, `Defect`, `Regent`, or
  `Necrobinder`.
- `STS2_BOOTSTRAP_ASCENSION`: a nonnegative ascension level.
- `STS2_BOOTSTRAP_PROFILE_SNAPSHOT`: a JSON file containing either
  `{"mode":"all_unlocks"}` or an episode's recorded `progress_snapshot`.

The profile snapshot is used only as the immutable unlock/encounter-history
input to run construction. This lets a recorded episode reproduce room RNG
without requiring or modifying a matching active `progress.save`.

When `STS2_BOOTSTRAP_RENDER` is set, the companion `finish_render` bridge
action waits the configured `STS2_BOOTSTRAP_RENDER_TAIL_FRAMES` and quits Godot
gracefully so Movie Maker finalizes its AVI. `STS2_BOOTSTRAP_FAST_MODE` accepts
`instant`, `fast`, or `normal`. Portable snapshot runs suppress progress-file
writes regardless of render mode.

See `headless/END_TO_END_REPLAY.md` and `headless/HANDOFF.md` for the validated
simulation and rendering workflows, limitations, and next work.
