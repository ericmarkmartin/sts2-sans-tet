# Cross-backend episode parity

The standalone simulator is fast, but Godot remains the semantic and rendering
reference. The parity runner replays a standalone episode action-by-action in
Godot, translates decisions by stable meaning rather than raw array position,
and compares normalized observable state after every source action.

## Proven passing run

On 2026-07-30, `episode-0012` replayed with:

- 124 standalone source actions consumed;
- 140 Godot actions;
- 16 separately labeled automatic actions for UI/reward progression;
- four combats plus Neow, maps, rewards, card picks, an event, an upgrade, and
  terminal floor-8 loss; and
- no semantic divergence.

The original profile-verified ignored local report is
`headless/parity-runs/parity-0007/parity.json`. After portable initialization
was added, the same episode matched again without access to the active profile
(`parity-0011` with the final bootstrap build).
Standalone episodes `0012` and `0013` also compared as exact deterministic
repeats across initial state, 124 actions, 124 result states, and terminal
summary.

An independently generated all-unlocks `episode-0014` also passed portable
replay: 109/109 standalone actions, 122 Godot actions (13 automatic), and
terminal floor-6 loss matched. Its ignored local report is `parity-0009`.

## Reproduce

Generate the standalone episode. To model a particular player profile, capture
its immutable run-generation inputs at generation time:

```bash
./headless/run_sts2_cli_episode.sh \
  --cli-dir ../sts2-cli \
  --progress-save "<active-modded-profile>/saves/progress.save" \
  --seed HEADLESSBENCH --policy-seed 0
```

Then replay it:

```bash
./headless/run_episode.sh \
  --replay-episode headless/episodes/episode-NNNN
```

Replay does not read the active profile. It validates the recorded canonical
snapshot checksum, materializes a launch-local JSON file, and injects that
snapshot plus the manifest's character, ascension, and seed into run
construction. Episodes generated without `--progress-save` record and inject
the explicit `all_unlocks` mode instead.

The command exits zero only on a complete match. It writes:

- `parity.json`: checkpoints, summary, and first divergence if present;
- `profile-snapshot.json`: the validated initialization input given to Godot;
- `actions.jsonl`: translated Godot actions with `automatic` and
  `source_action_index`;
- `states.jsonl`: post-action and asynchronous Godot states; and
- `game.log`: the Godot process log.

## Why profile provenance is recorded

STS2 generates event and encounter queues from one upfront RNG stream. The
available event set depends on revealed epochs, so two runs with the same seed
but different profiles can roll different encounters. A profile-backed
standalone episode records the revealed epoch IDs, encountered IDs, run count,
and canonical snapshot SHA-256 in `manifest.json`. The episode therefore
contains the run-shaping profile input needed for later replay; it does not
depend on the mutable file it was captured from.

The initial mismatch in this work was Shrinker Beetle versus weak slimes. It
was not simulation nondeterminism: the standalone backend had used
`UnlockState.all`, while Godot used the active profile. Passing the explicit
snapshot aligned the queues.

## Current comparison boundary

The comparator covers act/floor, HP/max HP/block/gold, relics, potions, event
options, map choices, combat round/energy/hand/enemies/pile membership and
upgrade state, card rewards, rest options, and terminal outcome.

It intentionally reconciles presentation-only Godot states such as event
Proceed buttons, individual reward claims, reward-screen Proceed, and
selection confirmations. Those actions are retained in the trace rather than
hidden.

This is semantic parity, not a byte-level engine checksum proof. Next coverage
work should add several fixed profile snapshots and seeds, every character,
act transitions, elites/bosses, shop/rest branches, potion use, and
checksum-level assertions where both backends expose comparable values.
