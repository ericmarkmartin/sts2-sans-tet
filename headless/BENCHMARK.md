# Godot `--headless` benchmark

## Environment

- Date: 2026-07-26
- Game: Slay the Spire 2 `v0.107.1`, release commit `59260271`
- Engine: custom Godot/MegaDot `4.5.1.m.12`, Mono
- Bridge: STS2MCP `v0.3.4`, port `15526`
- OS: Windows 10.0.26200, launched from WSL2
- CPU: AMD Ryzen 9 5900X, 12 cores / 24 logical processors
- RAM: 31.9 GB
- GPU rendering: unavailable/unused; Godot reported `N/A (headless)` and
  `Video Memory Used: 0.0B`

Command:

```text
SlayTheSpire2.exe --headless --audio-driver Dummy
```

The reproducible runner is `benchmark_headless.ps1`. It starts a fresh process,
waits for STS2MCP, samples only the process it created, and stops that process in
a `finally` block.

## Results

### Startup

| Milestone | Time |
|---|---:|
| STS2MCP root endpoint responds | 1.39 s |
| Main menu ready, from game log | 10.99 s |

The HTTP-ready milestone is not equivalent to a reset-ready environment. The
mod initializes early, while model, save, atlas, and main-menu loading continue
for roughly another ten seconds.

### Settled main-menu process

Observed from seconds 20–31 of a 30-second run:

| Metric | Result |
|---|---:|
| Working set | ~760 MB |
| Private bytes | ~749 MB |
| Threads | 60–62 |
| Idle CPU | ~6–12% of one logical core |
| GPU memory reported by Godot | 0 B |

There are two distinct memory plateaus: about 347 MB working set before main
menu loading, then about 760 MB after common assets and atlases load. Headless
mode prevents rendering-device allocation but does not prevent the game from
loading its UI scenes and texture atlases.

### HTTP reads after warmup

Sequential PowerShell `Invoke-WebRequest`, 100 requests per endpoint:

| Endpoint | Mean | p50 | p95 | Max | Throughput |
|---|---:|---:|---:|---:|---:|
| `/` | 11.93 ms | 11.74 ms | 13.31 ms | 20.36 ms | 83.8 req/s |
| `/api/v1/singleplayer` | 16.78 ms | 16.54 ms | 18.45 ms | 25.83 ms | 59.6 req/s |

These numbers include PowerShell client overhead and are not a transport
microbenchmark. Their useful conclusion is that full state construction adds
only about 5 ms over the same HTTP/client path at the main menu. A Python
keep-alive client should be benchmarked before changing transports.

### Autoslay exploratory run

With `--autoslay --seed HEADLESSBENCH`, the STS2MCP endpoint was ready in
3.27 seconds. At 17.5 seconds the process was still active and had reached:

- 873 MB working set
- 853 MB private bytes
- 61 threads
- approximately 23–66% of one logical core in the later samples

This is not yet a decisions/second benchmark; it establishes that autoslay and
STS2MCP both operate under the headless display driver.

### Direct bootstrap combat

The release build's `--bootstrap` route contains the intended direct-run
implementation, but no compiled `IBootstrapSettings` subtype. The companion mod
in `godot_bootstrap/` supplies deterministic settings and patches
`BootstrapSettingsUtil.Get()` to return them.

With a seeded Ironclad combat, preloading disabled, and Instant mode:

| Metric | Result |
|---|---:|
| Working set after combat startup | ~568 MB |
| Private bytes after combat startup | ~487 MB |
| Threads | 59–60 |
| Combat-state GET mean | 17.5 ms |
| Complete end-turn → next play-phase mean | 148.4 ms |
| Turn-cycle p50 / p95 / max | 149.8 / 161.1 / 202.7 ms |
| Complete turn cycles per second | 6.74 |

The fixed encounter completed nine cycles before the player died. Each cycle
includes the HTTP action, enemy turn, transition back to the player play phase,
and repeated state polling. It is therefore a useful lower-bound control-loop
measurement, not merely request throughput.

Direct combat consumes about 190 MB less working set and 260 MB less private
memory than loading through the main menu. It remains substantially larger than
the inert bootstrap scene (~296/196 MB), showing that combat assets/state—not
the HTTP bridge—now dominate incremental memory.

### Seeded random-policy episode and determinism

`benchmark_headless_episode.py` uses one persistent HTTP connection, plays
random legal cards, waits for each observable state change, and records every
action and full state as JSONL. It launches through PowerShell so it can record
and terminate the exact Windows process; it also fails before launch if the
bridge port is occupied.

Two cold runs used game seed `HEADLESSBENCH`, policy seed `0`, and Instant mode:

| Metric | Run A | Run B |
|---|---:|---:|
| Actions to rewards | 18 | 18 |
| Cold startup + combat | 4.975 s | 4.617 s |
| Actions/s including startup | 3.62 | 3.90 |
| Mean action → changed state | 40.69 ms | 39.99 ms |
| Initial / final HP | 80 / 74 | 80 / 74 |

After excluding timestamps and performance summaries, all 37 semantic records
(18 action records and 19 full-state records) matched exactly. This validates
determinism for the current fixed combat and random policy, not yet for
in-process resets or complete runs.

### Warm reset

The bootstrap companion exposes guarded `reset` and `reset_status` actions. A
reset calls the game's own `RunManager.CleanUp()`, rebuilds the seeded run, and
re-enters direct combat without restarting Godot. Completion IDs prevent a
client from mistaking the previous combat for the newly reset one.

Five consecutive resets in one process, measured until the player play phase:

| Metric | Result |
|---|---:|
| Mean | 1,067.3 ms |
| Min / max | 950.0 / 1,141.8 ms |
| Exact initial-state matches | 5 / 5 |

This is roughly 4–5 times faster than the observed cold startup plus combat
readiness. It still includes scene replacement, run setup, room entry, initial
draw, and bridge polling.

### Built-in replay archival

When given `--mcr-source`, the episode runner waits for a fresh built-in
`latest.mcr` after combat, copies it to a combat-indexed immutable filename,
computes SHA-256, and appends a `combat_replay` link to the JSONL trace. The
first validation artifact was 1,855 bytes with SHA-256
`c3c83982d84080b57631b5a4c7a1504e4547d2fee7e17f7bc6c737d3068c77f1`.

### Full-run lifecycle

`--full-run` enters the normal act flow and drives initial card selection,
event, map, combat, and game-over states. The first deterministic random-policy
validation reached floor 2 and died after 33 external actions:

| Metric | Result |
|---|---:|
| Cold startup + episode | 8.55 s |
| Final state / HP | game_over / 0 |
| Actions/s including startup | 3.86 |
| Archived combat replays | 1 |
| Loss replay size | 2,322 bytes |

The loss path retains an active replay writer until cleanup, so the companion
exposes a narrow `write_replay` action that invokes the game's public
`RunManager.WriteReplay(stopRecording: true)` after combat completion. This
ensures losses are archived before the headless process exits.

## Interpretation

Godot `--headless --bootstrap` is viable functionally and removes both GPU
rendering and main-menu overhead. Direct-combat instances are still too large
for the original thousands-of-processes target: 16 instances would consume
roughly 7.8 GB of private memory before later-run growth. It is valuable as:

- a near-term single/few-environment training and correctness backend;
- a reference implementation for seeded state/action fixtures; and
- a baseline against which a standalone stubbed backend must improve.

The observed HTTP cost is not the primary bottleneck at this point. Engine
startup, common-asset loading, per-action animation/timing, and one-process
memory are higher-priority targets.

## Remaining Phase B0 measurements

1. Compare normal and fast modes against the measured Instant baseline.
2. Improve the random policy enough to exercise multi-combat, boss, and act
   transition replay sets.
3. Test two concurrent instances only after isolating STS2MCP ports and
   save/profile paths; launching them against shared state would make the result
   unsafe and ambiguous.
4. Validate archived `.mcr` playback in a pinned rendered build.
5. Compare a rendered run on the same machine if visual mode baseline numbers
   are needed.
