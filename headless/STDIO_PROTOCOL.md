# Standalone stdio protocol

Start one persistent simulator process:

```bash
dotnet run --project headless -- stdio \
  --game-data-dir "<game>/data_sts2_windows_x86_64"
```

Input and output are newline-delimited JSON. Include `request_id` on every
request; the corresponding terminal response echoes the same JSON scalar.
Messages with a `stage` and no `request_id` are lifecycle diagnostics and may
be recorded or ignored by a protocol client.

## Commands

### Health

```json
{"cmd":"health","request_id":1}
```

Reports the loaded assembly, observation schema, active seed, and whether an
episode has been reset and is ready.

### Reset

```json
{"cmd":"reset","request_id":2,"seed":"HEADLESSBENCH"}
```

Cleans up the prior run, creates a deterministic Ironclad run, enters the test
encounter, enables canonical checksum tracking, and returns the initial
`sts2.standalone.combat.v1` observation. Repeated reset is supported in the same
process.

### Observe

```json
{"cmd":"observe","request_id":3}
```

Returns the current observation without mutating game state. It fails if no
episode has been reset.

### Step

Submit one action exactly as identified by `legal_actions`:

```json
{"cmd":"step","request_id":4,"action":"play_card","card_index":1,"target_combat_id":1}
{"cmd":"step","request_id":5,"action":"end_turn"}
```

The service validates the complete card/target pair before constructing a game
action. It submits valid actions through
`ActionQueueSynchronizer.RequestEnqueue`, waits for completion, and returns the
post-action observation. `end_turn` additionally waits for the next stable
player play phase.

Invalid or stale actions return an error and do not mutate state:

```json
{"error":"Requested card/target pair is not a legal action","error_type":"System.InvalidOperationException","request_id":4}
```

### Shutdown

```json
{"cmd":"shutdown","request_id":6}
```

Returns one successful response and exits zero.

## Current scope

The v1 service hosts deterministic singleplayer combat against the fixed
Fuzzy Wurm/Crawler test encounter. It currently accepts `play_card` and
`end_turn`. Potions, player-choice continuations, multi-enemy regression cases,
full-run navigation, and automatic episode artifact writing are later protocol
increments.

