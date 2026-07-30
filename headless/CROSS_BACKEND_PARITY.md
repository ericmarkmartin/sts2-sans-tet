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

The profile-verified ignored local report is
`headless/parity-runs/parity-0007/parity.json`.
Standalone episodes `0012` and `0013` also compared as exact deterministic
repeats across initial state, 124 actions, 124 result states, and terminal
summary.

## Reproduce

Generate the standalone episode with the same profile inputs Godot will use:

```bash
./headless/run_sts2_cli_episode.sh \
  --cli-dir ../sts2-cli \
  --progress-save "<active-modded-profile>/saves/progress.save" \
  --seed HEADLESSBENCH --policy-seed 0
```

Then replay it:

```bash
./headless/run_episode.sh \
  --replay-episode headless/episodes/episode-NNNN \
  --progress-save "<active-modded-profile>/saves/progress.save"
```

For a profile-backed episode, the command refuses to launch unless the active
profile's canonical run-generation snapshot matches the one in the episode
manifest. Raw progress-file hashes may change when Godot saves incidental
statistics; the canonical unlock snapshot is the parity identity.

The command exits zero only on a complete match. It writes:

- `parity.json`: checkpoints, summary, and first divergence if present;
- `actions.jsonl`: translated Godot actions with `automatic` and
  `source_action_index`;
- `states.jsonl`: post-action and asynchronous Godot states; and
- `game.log`: the Godot process log.

## Why profile provenance is required

STS2 generates event and encounter queues from one upfront RNG stream. The
available event set depends on revealed epochs, so two runs with the same seed
but different profiles can roll different encounters. A profile-backed
standalone episode records the revealed epoch IDs, encountered IDs, run count,
and canonical snapshot SHA-256 in `manifest.json`.

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
