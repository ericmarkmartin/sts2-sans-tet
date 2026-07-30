# Headless Backend — Implementation Plan

## Goal

Build a deterministic, inspectable training backend for STS2. Use the real game
under Godot `--headless --bootstrap` as the working reference backend; retain
standalone .NET as a conditional optimization if profiling justifies its much
higher implementation risk.

This is now a two-backend system:

- **Near-term training baseline:** run the real game with Godot's `--headless`
  display driver as the rendering and semantic reference.
- **High-throughput simulation baseline:** run the real managed game logic
  through the pinned `sts2-cli` fork, then replay episode action traces in
  Godot for parity and video.

Both backends now execute full episodes. Keep cross-backend replay parity as a
release gate for standalone changes.

## Current status (2026-07-30)

- A compatibility branch of `wuhao21/sts2-cli` is now pinned at
  `ericmarkmartin/sts2-cli@5e3e161`. It builds against the installed current
  game, completes full standalone episodes, and uses the standard
  `RunState.CreateForNewRun` mechanics initialization while retaining
  `SetUpTest` only for presentation/persistence suppression.
- The fork exposes versioned `sts2-cli.observation.v1` decisions. Human mode
  includes visible pile membership without leaking private draw order;
  authoritative mode additionally exposes engine pile order. Canonical
  observation hashes support divergence detection.
- `headless/sts2_cli_episode.py` adapts that protocol to this repository's
  `initial.state` / `actions.jsonl` / `results.jsonl` / `manifest.json`
  contract. `headless/run_sts2_cli_episode.sh` is the stable, reusable command
  boundary. `--progress-save` captures the run-shaping unlock snapshot
  (revealed epochs, seen encounters, and run count) and fingerprints it in the
  manifest; seed alone is not sufficient provenance because room generation
  consumes RNG according to unlocked content.
- `headless/replay_trace_godot.py` semantically translates a standalone episode
  into Godot actions, labels presentation-only actions as automatic, and
  compares normalized checkpoints after every source action.
- Episode `0012` passed full cross-backend replay: all 124 source actions,
  140 Godot actions (16 automatic), four combats, rewards/card selections,
  an event, map movement, a Fishing Rod upgrade, and terminal floor-8 loss
  matched with no semantic divergence. See
  `headless/CROSS_BACKEND_PARITY.md`.
- Profile-backed episodes `0012` and `0013` were exact deterministic repeats:
  identical initial state, all 124 actions, all 124 result states, and terminal
  summary after timing fields were excluded.
- The standalone fork still produces no `.mcr`. Godot remains the rendering
  backend; the now-validated episode trace can reconstruct the whole run, while
  archived `.mcr` remains the highest-fidelity combat artifact when available.

- Phase A passed: `sts2.dll` loads in .NET 9, all types required by the probe
  resolve, and `MegaCrit.Sts2.Core.Runs.RunManager` constructs successfully.
- `RunManager.StartRun(...)`, assumed below, does not exist. The test-oriented
  startup seam is `RunState.CreateForTest(...)` followed by
  `RunManager.SetUpTest(...)`.
- Standalone Phase B now creates a complete seeded `RunState` and exits zero.
  The host mirrors `ModelIdSerializationCache.Init()` without its three
  `Godot.Mathf` calls and Godot-backed final log, installs the game's test mode,
  and supplies the narrow in-memory progress object graph read during player
  construction. Against `v0.107.1`, it reproduces the rendered game's cache
  counts and hash exactly: 20 categories, 1,622 entries, 57 epochs, hash
  `3954186980`.
- Standalone manager setup now passes. A narrow pre-initialization patch keeps
  the game's logger on its console backend instead of querying the uninstalled
  Godot editor callback. `RunManager.SetUpTest(...)` and `Launch()` retain the
  complete shared mechanics graph: action queues/executor, checksum tracking,
  player choices, map/event/reward/rest synchronization, combat state
  synchronization, and the replay-writer service. The writer is currently
  disabled by the game's `TestMode`, so standalone `.mcr` output is not yet a
  passing capability.
- `phase-c-combat` now enters a real deterministic Ironclad combat, performs
  start-of-combat hooks, draws the opening hand, generates the normal checksum,
  and reaches player play phase without starting Godot. Two host correctness
  fixes were required: configure the canonical `RunManager.Instance` rather
  than a second manager, and explicitly create an Ironclad player because the
  game's default `CreateForTest` character (`Deprived`) intentionally has no
  starter deck.
- The standalone save graph disables FTUE presentation through the game's
  normal profile setting. This prevents tutorial nodes from being requested;
  it does not alter mechanics. `TestMode` supplies the game's intended
  noninteractive timing and visual-suppression behavior.
- `phase-c-action-cycle` now submits a targeted Strike through
  `ActionQueueSynchronizer.RequestEnqueue`, awaits the canonical action,
  submits `EndPlayerTurnAction`, executes the enemy turn, and reaches turn two
  in player play phase. It asserts energy, hand, HP, turn, and checksum
  transitions. On the reference seed the checksums deterministically change
  from `3932430620` to `1034061027`.
- `phase-d-observation` emits the versioned
  `sts2.standalone.combat.v1` schema from authoritative models. It includes
  explicit information policy, all combat piles, numeric card variables,
  powers/relics/potions, enemy intent damage, checksum status, and legal
  card/target pairs without consulting scene nodes.
- The persistent standalone stdio service now implements `health`, repeatable
  deterministic `reset`, `observe`, validated `play_card` / `end_turn` steps,
  and `shutdown`. A tested reset/play/end/reset sequence returns to the exact
  initial decision state without restarting the process.
- Earlier native callback failures reproduced in both Linux .NET and a
  self-contained Windows .NET 9 host. Resolving the real `GodotSharp.dll` is
  enough for managed type loading, but engine callbacks still require either
  the running engine or an explicitly isolated compatibility seam.
- The compatibility probe and detailed findings live in `headless/`.
- The repository now has a pinned `nix develop` shell with .NET 9, Python 3.11,
  and `uv`.
- Initial Phase B0 results are in `headless/BENCHMARK.md`: Godot headless is
  functional and reports zero GPU memory. The companion bootstrap mod bypasses
  the main menu and starts deterministic combat at roughly 568 MB working set /
  487 MB private bytes. In Instant mode, end-turn through the next player play
  phase averages 148 ms (6.74 complete turn cycles/second). This is suitable for
  a modest number of reference/training environments, not the original
  thousands-of-processes target.
- A seeded random policy completed direct combat in 18 actions. Two independent
  cold runs produced byte-for-byte identical action payloads and full game-state
  payloads after timestamps were excluded.
- Five guarded in-process resets averaged 1.067 seconds to a player-ready
  combat, and all five initial states matched exactly.
- The runner can archive and hash the built-in per-combat `.mcr` before the game
  overwrites `latest.mcr`, linking it into the episode manifest.
- Full-run mode now enters the normal act lifecycle and writes self-contained
  `episode-NNNN/` directories. The first validation traversed initial selection,
  event, map, combat, and game over in 33 actions, with the loss replay archived.
- Episodic evaluation is intentionally binary: loss `0`, win `1`, and
  nonterminal/incomplete `null`.
- `benchmark_headless_episode.py` now owns and terminates the exact Windows game
  process it starts, rejects an occupied bridge port before launch, preserves a
  game log on failure, and writes an append-only JSONL episode trace.

## Repository layout

New top-level `headless/` directory in `sts2-sans-tet`:

```
sts2-sans-tet/
├── headless/
│   ├── STS2Headless.csproj      # .NET 9 console app, references sts2.dll
│   ├── Program.cs                # entrypoint: stdio loop
│   ├── Host/                     # Godot type stubs, assembly resolver
│   ├── Serialization/            # state → JSON (mirrors STS2MCP shape)
│   ├── Actions/                  # JSON → RunManager/CombatManager calls
│   └── README.md                 # build + run instructions
├── sts2_rl/
│   ├── headless_backend.py       # spawns + talks to the .NET subprocess
│   └── env.py                    # rewritten on top of the backend
└── ...
```

Rationale: keeping .NET inside `sts2-sans-tet` matches the project's end goal (self-contained RL harness). It mirrors the layout of the old custom mod (`mod/` was C#, Python at root). Reserves the option of a separate STS2MCP-parity project later if we want.

## Phased execution

### Phase A — Load experiment  (est. 2–4h, high risk)

**Question this answers:** does `sts2.dll` load at all without Godot, and can we construct a `RunManager`?

**Steps:**
1. `dotnet new console -f net9.0` in `headless/`.
2. Add a `Reference` to `sts2.dll` in the csproj using an `STS2GameDataDir` MSBuild property (same pattern as STS2MCP's csproj).
3. On startup, register an `AssemblyLoadContext.Resolving` handler that looks for dependent DLLs (`GodotSharp.dll` etc.) in the game data dir.
4. Try to `Type.GetType("RunManager")` or equivalent, then construct it. Log every exception in full.

**Decision points based on what breaks:**
- **Loads clean, construction works** → proceed to Phase B.
- **Godot type-load errors** → catalog which Godot types are hit at load/construction, decide whether to stub them (write dummy classes in `Host/`) or force resolution to real Godot DLLs.
- **`SteamAPI_Init` or ownership check** → write a `steam_api.dll` stub that returns success, or reconsider whether headless is viable.
- **Something else** → adjust.

**Deliverable:** a short writeup in `headless/README.md` documenting exactly what loads, what doesn't, and what the stubbing surface looks like.

### Phase B0 — Benchmark Godot `--headless`  (next)

**Question this answers:** is the real engine without rendering already cheap
and fast enough for training?

Run the installed game with the existing STS2MCP mod using `--headless`. Measure:

1. Process startup time and time until the STS2MCP health/state endpoint responds.
2. Working set, private bytes, thread count, idle CPU, and child processes after
   startup settles.
3. Reset latency and action latency over several episodes.
4. Decisions/second during a deterministic random-policy smoke test.
5. Whether audio, Steam, saves, focus handling, or scene transitions block in
   headless mode.
6. Whether two instances can run concurrently with isolated save/config paths
   and distinct STS2MCP ports.

Record the exact executable arguments, game version, machine, sample count, and
raw measurements in `headless/BENCHMARK.md`. Compare against a normal rendered
run on the same machine when possible.

**Decision:**

- If one instance is reasonably small and multi-instance operation works,
  promote Godot-headless to the initial training backend.
- If it is too expensive, use the failure traces below to scope a standalone
  stub assembly before proceeding.

### Phase B1 — Standalone model/bootstrap  (passed through player-ready combat)

**Goal:** initialize `ModelDb` and create a `RunState` without native Godot.

Known required sequence:

1. Complete or explicitly skip `ModManager` initialization.
2. `ModelDb.Init()`.
3. `ModelIdSerializationCache.Init()`.
4. `ModelDb.InitIds()`.
5. `RunState.CreateForTest(...)`.
6. `RunManager.SetUpTest(...)`.
7. `RunManager.Launch()`.

The working host bypasses the model-cache `Mathf` calls, selects the console
logger before its static initializer, and uses the game's test/noninteractive
paths to suppress visuals and waits. It does not replace `GodotSharp.dll` or
remove semantic shared services. Continue growing host-owned interfaces from
observed call paths and keep the compatibility inventory current.

**Stop condition:** if reaching `RunState` requires broad scene-tree,
resource-loading, or generated Godot binding behavior, reassess the standalone
approach rather than recreating Godot piecemeal.

### Phase B2 — Drive one combat turn  (passed)

**Goal:** start a run, enter combat, play a card, end turn, observe result — all in-process, no JSON yet.

**Steps:**
1. `phase-c-action-cycle` selects a legal enemy-targeting card from the
   authoritative hand.
2. It submits `PlayCardAction` and `EndPlayerTurnAction` through the real
   synchronizer and action executor.
3. It waits for the next stable player play phase and verifies HP, energy,
   piles, turn number, and checksums.

**Deliverable:** `phase-c-action-cycle` is the integration smoke test proving
the game logic is drivable without Godot.

### Phase C — Full training protocol  (passing)

**Goal:** expose complete run decisions with an explicit information policy,
record portable episodes, and continuously compare them with Godot.

The standalone backend now covers map, event, combat, reward, rest-site, shop,
and terminal decisions. Its episode adapter and Godot semantic replay have
passed one complete 124-action run.

**Steps:**
1. Define versioned `reset`, `get_state`, `play_card`, and `end_turn` messages.
2. Include explicit valid-action data and stable entity/card identifiers; do
   not make Python infer legality from presentation fields.
3. Run a seeded scripted combat twice and assert deterministic observations.
4. Gate standalone changes on representative cross-backend episode replay.
5. Add direct potion-use coverage and broaden seeds, characters, events,
   shops, rest sites, elites, bosses, and act transitions.

**Deliverable:** a versioned full-run protocol with deterministic fixture tests
and a semantic Godot replay oracle.

### Phase C1 — Replay and provenance artifacts

Retain two complementary artifacts:

1. Archive the game's profile-scoped `replays/latest.mcr` immediately after
   every combat. `CombatReplayWriter` captures internal net actions, choices,
   hook/resume ordering, checksums, and full combat-state snapshots; a pinned
   rendered game build can play it back.
2. Keep our append-only episode JSONL as the primary run-level record. It must
   cover non-combat decisions, timestamps, external actions, periodic full
   states, seeds/options, game and mod hashes/configuration, and links to each
   archived `.mcr`.

An `.mcr` alone is insufficient: it is combat-only, contains no timestamps or
frames, and `latest.mcr` is overwritten after each combat. Conversely, a JSONL
trace alone cannot reproduce the game's exact internal action/checksum stream.
For post-hoc video, replay archived `.mcr` files in a rendered pinned build and
capture them; reconstruct non-combat transitions from the episode trace.

### Phase D — Transport chosen by backend

The standalone backend should use stdio NDJSON. The Godot-headless backend may
initially retain STS2MCP HTTP because that path already works; benchmark before
replacing it. Do not attribute engine overhead to HTTP without measuring it.

**Wire format:**
- Line-delimited JSON on stdin/stdout.
- Each stdout line is one message: state observation or ack.
- Each stdin line is one command: `{"cmd": "get_state"}`, `{"cmd": "act", "action": {...}}`, `{"cmd": "reset"}`, `{"cmd": "shutdown"}`.
- Errors → `{"error": "..."}`; log lines go to stderr, never stdout.

**Steps:**
1. `Program.cs` reads stdin lines in a loop, dispatches to the right serializer/action handler, writes response line to stdout.
2. All game logging redirected to stderr.
3. Clean shutdown on EOF or `shutdown` cmd.

**Deliverable:** `dotnet run` produces a headless process that speaks the protocol on stdio. Manually pokeable with `echo '{"cmd":"get_state"}' | dotnet run`.

### Phase E — Python backend + Gym wrapper

**Goal:** RL-side plumbing.

**Steps:**
1. `sts2_rl/headless_backend.py` — subprocess wrapper. `Popen` the .NET binary, write cmds to its stdin, read responses from stdout. Handles reset/step/close.
2. Rewrite `sts2_rl/env.py` only after the selected backend passes reset/step.
   Preserve old files until their replacement has tests; delete them in a
   separate cleanup change.
3. Port `test_sts2mcp_random.py`'s state-dispatch logic into the env or a random-policy helper, so we get an end-to-end smoke test.

**Deliverable:** `uv run python test_headless_random.py` runs continuous episodes against the headless backend at whatever speed it manages. Establishes a throughput baseline for tuning.

### Phase F — Multi-env parallelism  (deferred)

Once single-env works: `SubprocVecEnv`-style wrapper, N headless subprocesses in parallel. Straightforward given the stdio design. Not doing this in the initial pass.

## Open questions to resolve as we go

1. **Steam handshake.** Does the game do a Steam ownership check on startup? Answered in Phase A.
2. **Godot stubbing surface.** How many Godot types are actually referenced by construction/gameplay code paths? Answered incrementally through A → B.
3. **Game data files.** Does the game read card definitions / balance data from disk at runtime? If so, the headless process needs the game data dir accessible.
4. **License/legal.** Not blocking — `sts2.dll` and game data stay on machines with a legitimate copy, nothing gets committed or distributed. If we ever want to open-source, the headless binary must assume users bring their own game files.
5. **Determinism / seeding.** Direct bootstrap combat is deterministic for the
   tested `HEADLESSBENCH` game seed and policy seed 0: 37 action/state records
   matched exactly across two cold runs. Extend this assertion to resets and
   complete runs.
6. **Throughput target.** No fixed goal in the initial pass. Measure and iterate — first make it work.

## What NOT to do in this pass

- No MCP server exposure. Deferred until protocol layer stabilizes.
- No multi-env parallelism (Phase F is a followup).
- No RL training. That's the next milestone after headless works.
- Keep STS2MCP changes narrow and version-pinned. The current game required a
  small compatibility patch; new training lifecycle endpoints should live
  behind an explicit protocol version.
- No premature abstraction over "backends." One backend (headless) is enough until there's a second consumer. If we later want to swap in a Godot backend for eval, we can extract the interface then.
