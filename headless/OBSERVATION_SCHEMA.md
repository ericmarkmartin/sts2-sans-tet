# Standalone observation schema

## `sts2.standalone.combat.v1`

`phase-d-observation` emits a `standalone_observation` milestone containing the
first versioned, engine-independent policy observation.

The schema's information policy is `omniscient_authoritative`. It reports the
complete authoritative state available to the standalone simulator, including
draw-pile order. A human-equivalent or partially observed evaluation should be
implemented as a projection of this schema; it should not remove state from the
simulator itself.

## Top-level fields

| Field | Meaning |
| --- | --- |
| `schema` | Stable schema identifier |
| `information_policy` | Visibility contract applied by the serializer |
| `decision` | Combat phase, side, round/turn, and whether player actions are enabled |
| `player` | Numeric player state, resources, powers, relics, potions, and all combat piles |
| `enemies` | Stable model/combat IDs, HP/block, powers, and current intents |
| `legal_actions` | Actions accepted at this decision point with card indices and target combat IDs |
| `checksum` | Whether canonical checksum tracking is active and its next checkpoint ID |

Cards contain their model ID, type, rarity, upgrade state, energy/star costs,
target type, and evaluated dynamic variables such as damage, block, and power
amounts. `can_play` appears only for cards in hand. Cards in other piles remain
fully described but are not presented as immediately playable.

Enemy attack intents include `damage_per_hit` and `repeats`, calculated from the
game's authoritative intent model without localized UI text.

## Legal actions

The initial combat schema emits:

```json
{"action":"play_card","card_index":1,"card_id":"STRIKE_IRONCLAD","target_combat_id":1}
{"action":"end_turn"}
```

`legal_actions` is derived from `CardModel.CanPlay()` and
`CardModel.IsValidTarget(...)` while the player is in `PlayerTurnPhase.Play`.
It is not inferred from UI controls.

Later schema revisions must use a new schema identifier when changing field
meaning or action identity. Additive optional fields may remain within v1.

