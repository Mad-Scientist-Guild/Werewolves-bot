# Developer guide — architecture and data

This guide covers how the bot is put together: the layers, the game-state dataclasses, how state reaches the
database, and what happens between a player's command and a message in Discord. For writing roles, see
[Developer guide - adding a role](Developer%20guide%20-%20adding%20a%20role.md).

**Contents**
1. Layers
2. The state model
3. Serialisation
4. The database
5. Life of a change
6. A phase transition
7. Effects and the outbox
8. Channel access
9. Registries and extension points
10. Where to change what

---

## 1. Layers

```mermaid
flowchart TB
    subgraph Discord ["Discord-facing"]
        BOT["bot.py<br/>startup, error handling"]
        COGS["Cogs/<br/>/game /setup /gm /lynch /mayor /me<br/>scheduler, activity, realtime"]
        RC["Roles/*  RoleCommands<br/>role slash commands"]
    end
    subgraph Services ["Services/ - glue"]
        GS["GameService<br/>lock + save + rollback"]
        W["GameWorker<br/>follow-up after every change"]
        ED["EffectDelivery<br/>outbox to Discord"]
        CM["ChannelManager<br/>create + reconcile permissions"]
        AP["AuditPoster<br/>events + reports to #mod-log"]
        V["views<br/>persistent buttons and menus"]
    end
    subgraph Core ["Core/ - pure game engine (no Discord)"]
        ST["state.py dataclasses"]
        EN["actions, resolution, players, lifecycle,<br/>transitions, lynch, decisions, gm_tools,<br/>voting, access, clock, realtime"]
        RL["Roles/* Role and Modifier classes"]
    end
    subgraph Storage ["Storage/"]
        CO["codec.py<br/>state to JSON"]
        DB[("db.py<br/>SQLite")]
    end
    BOT --> COGS & RC
    COGS --> GS
    RC --> GS
    GS --> EN
    EN --> ST
    RL --> EN
    GS --> CO --> DB
    GS -. notify .-> W
    W --> ED & CM
    AP --> DB
    ED --> DB
```

**The dependency rule:** `Core/` never imports `discord` or `Services/`. The engine only changes dataclasses and
queues *effects* (data saying "post this message"). That's why the whole game can be tested without Discord or a
database, and why a night can be previewed on a copy.

Shared service instances live on `runtime` in [Services/runtime.py](../Services/runtime.py) (`runtime.games`,
`runtime.db`, `runtime.channels`, ...). They're set up in `WerewolvesBot.setup_hook` in [bot.py](../bot.py).

---

## 2. The state model

Everything about one game is a single `GameState` object ([Core/state.py](../Core/state.py)). Players and channels
are referenced **by id only** (Discord user ids, channel ids), so the state can be stored as JSON, deep-copied for
the night preview and snapshotted for rollbacks. The Discord layer looks the objects up from the ids.

```mermaid
classDiagram
    class GameState {
        guild_id, game_id
        phase, day, paused, winner
        settings: Settings
        role_pool: dict
        assignment_preview: dict
        channels: dict
        categories: dict
        created_channels, created_categories: list
        discord_roles: dict
        mayor, mayor_successor, lockdown
        second_lynch_by, first_death_seen
        catch_up_approved, newspaper_published_day, newspapers
        seeds, counters, data: dict
        next_transition: Transition
        pending_logs - transient
        pending_effects - transient
        pending_reports - transient
    }
    class Player {
        user_id, display_name
        life: LifeState
        faction, original_role
        family, private_chat
        public_role
        last_active_at, inactivity_level
        true_faction()
        actors()
    }
    class RoleBase {
        <<Polymorphic>>
        owner, uses_spent, last_used
    }
    class Role
    class Modifier
    class Chat {
        key, kind: ChatKind, name
        channel_id
        members: dict id to Membership
        archived
    }
    class SubmittedAction {
        id, actor, source, ability
        resolves_at, targets, params
        status: ActionStatus
    }
    class Ballot {
        kind, day, is_open
        votes, shown_as
    }
    class Decision {
        kind, chooser, options
        resolved, choice
    }
    class Settings {
        schedule: Schedule
        newspaper_url
        role_overrides
        notify_blocked_actions
    }
    GameState "1" *-- "*" Player : players
    GameState "1" *-- "*" Chat : chats
    GameState "1" *-- "*" SubmittedAction : actions
    GameState "1" *-- "*" Ballot : ballots + archive
    GameState "1" *-- "*" Decision : decisions
    GameState "1" *-- "*" Eavesdrop : eavesdrops
    GameState "1" *-- "*" YesNoQuestion : questions
    GameState "1" *-- "*" TelepathMessage : telepathy
    GameState "1" *-- "*" NightOverride : night_overrides
    GameState "1" *-- "1" Settings
    Player "1" *-- "0..1" Role : role
    Player "1" *-- "*" Modifier : modifiers
    Player "1" *-- "*" Condition : conditions
    Player "1" *-- "*" DeathRecord : deaths
    Ballot "1" *-- "*" VoteRecord : history
    Eavesdrop "1" *-- "*" OverheardMessage : messages
    RoleBase <|-- Role
    RoleBase <|-- Modifier
```

Some concepts that aren't obvious from the field names:

- **Life states.** `ALIVE`, `DEAD`, `SKELETON` (raised by the Lich: not alive, not dead) and `PERMA_DEAD` (a
  skeleton that died again).
- **Factions.** `player.faction` is the base faction. `player.true_faction()` lets modifiers override it; the most
  recently added override wins. Investigations use `apparent_faction`, which roles can disguise.
- **A `Chat` is any game channel with members**, including private channels (`PRIVATE`), the village (`VILLAGE`)
  and the dead chat (`DEAD`). Leaving a chat sets the membership to `FORMER` (read-only), never removes it. `archived` makes
  the whole chat read-only.
- **Houses are families.** `state.house_of(pid)` returns the family's chat key (or `house:<id>` for a player
  without a family). Locks, blessings, the Insomniac and the Diviner all work per house.
- **Actions** are stored as data. `resolves_at` says when an action resolves (`night:3`, `dusk:3` or `instant`).
  `status` records what happened (pending, replaced, cancelled, resolved, blocked, failed). Old actions are kept
  for the record.
- **Everything the engine itself uses is a typed field** on `GameState` (e.g. `second_lynch_by`,
  `first_death_seen`, `newspapers`). **`state.data`** is only for data owned by one role or faction (the coven
  kill list, coven links, Brother invites). The owning `Roles/` module reads and writes it through its own
  helpers (`_coven.kill_list(state)`), and its keys start with the owner's name. Keys must be strings.
- **Transient fields.** `pending_logs`, `pending_effects` and `pending_reports` are never stored as state. They
  are what `state.log(...)`, `state.emit(...)` and `state.report(...)` collect during one change. The service
  writes them to their own tables in the same transaction, then clears them.

---

## 3. Serialisation

[Core/serialize.py](../Core/serialize.py) converts any dataclass tree to JSON-friendly data and back.

- `dump(obj)` handles dataclasses, enums (stored as their value), lists, sets, dicts (int and enum keys become
  strings) and plain values. Fields declared with `transient(...)` are skipped.
- `load(Type, data)` uses the class's type hints to rebuild everything, including `dict[int, Player]` keys,
  enums, `X | None` and nested dataclasses.
- **Polymorphism.** A class family deriving from `Polymorphic` is written with a `"__type__"` tag. A field typed as
  `Role` then comes back as a `Seer`, `Witch` and so on. Families: `"actor"` (roles and modifiers, tagged by
  `name`) and `"effect"` (tagged by class name).
- **Forgiving by design.** Missing fields get their defaults and unknown keys are ignored, so adding or removing
  a field on a role doesn't break a stored game. Loading a game that still contains a role or effect whose class
  no longer exists fails with a clear error.

[Storage/codec.py](../Storage/codec.py) wraps this into `encode(state) -> str` and `decode(text) -> GameState`.
There is no versioning or migration layer: the bot only runs one event at a time, so a game is always loaded by
the code that saved it. If you change the stored shape in a way the forgiving loader can't handle (e.g. renaming
a field), finish or delete running games first.

---

## 4. The database

SQLite (WAL mode) through `aiosqlite`, in [Storage/db.py](../Storage/db.py). There is one connection; every write
goes through `Database.write_lock`, so writes from different coroutines never mix inside one transaction.

```mermaid
erDiagram
    games ||--o{ snapshots : "before every transition"
    games ||--o{ reports : "previews, finals, dusk..."
    games ||--o{ events : "audit log"
    games ||--o{ outbox : "effects to deliver"
    games {
        int id PK
        int guild_id
        text status "setup / active / ended"
        text phase
        int day
        text state "GameState as JSON"
        text created_at
        text updated_at
    }
    snapshots {
        int id PK
        int game_id FK
        text label
        int day
        text phase
        text state
        text created_at
    }
    reports {
        int id PK
        int game_id FK
        int guild_id
        int day
        text title
        text body
        int posted
    }
    events {
        int id PK
        int game_id FK
        int guild_id
        text at
        text category
        text message
        int actor_id
        text target_ids
        text data
        int alert
        int posted
    }
    outbox {
        int id PK
        int game_id FK
        text effect "Effect as JSON"
        text delivered_at
        int attempts
        text error
    }
```

| Table | Written | Read / updated |
|---|---|---|
| `games` | `create_game`; every change via `commit_game` (the whole state, one row) | on startup (`active_games` loads every stored game, ended ones too) |
| `snapshots` | before every transition, before game start/end, before a rollback | `/gm clock snapshots`, `/gm clock rollback` |
| `reports` | with the change that produced them | the AuditPoster posts them and sets `posted` |
| `events` | `state.log(...)` (same transaction), or `add_event` (rejected commands, errors, permission syncs) | the AuditPoster posts them; `/gm log` searches them |
| `outbox` | `state.emit(...)` (same transaction) | EffectDelivery sets `delivered_at`, or counts `attempts` and records the `error` |

**One transaction per change.** `commit_game` writes the new state, its events, effects, reports and (if asked) the
snapshot of the previous state together. A crash can't leave a saved state without its messages, or messages
without their state.

**Nothing is deleted while a game exists.** Ended games stay in the database and are reloaded after a restart.
Only `/game delete` removes the game's rows from all five tables, after a confirmation. There is one game per
server at a time: `/game create` refuses until the previous game is deleted.

---

## 5. Life of a change

A player uses `/seer check target:Alice`:

```mermaid
sequenceDiagram
    actor P as Player
    participant RC as SeerCommands (RoleCommands.use)
    participant GS as GameService.mutate
    participant EN as Core (actions.submit)
    participant DB as Database
    participant W as GameWorker
    participant ED as EffectDelivery
    participant CM as ChannelManager
    participant AP as AuditPoster
    P->>RC: /seer check target
    RC->>GS: async with mutate(guild)
    GS->>GS: take the game lock, deepcopy backup
    GS->>EN: submit(state, ...)
    EN->>EN: validate, store SubmittedAction,<br/>state.log(...)
    EN-->>GS: action
    GS->>DB: commit_game(state + events + effects + reports)
    GS-->>RC: (lock released)
    RC-->>P: ephemeral confirmation
    GS-)W: on_change(handle) = GameWorker.wake
    W->>CM: ensure_chat_channels (any chat without a channel)
    W->>ED: deliver(outbox)
    ED->>DB: mark delivered
    W->>CM: sync permissions and public roles
    W-)AP: wake
    AP->>DB: unposted events and reports
    AP->>AP: post batched embeds to #mod-log
```

**When something fails:**
- If anything inside `mutate` raises (a `GameError` from validation, a bug, or a database error), the state is
  restored from the backup and nothing is saved.
- A `GameError` becomes a red ephemeral reply and a `REJECTED` event.
- Any other exception becomes an `ERROR` event that pings the GMs, and the traceback goes to `logs/bot.log`.

**Commands and the scheduler never interleave:** both go through `mutate`, which holds the game's
`asyncio.Lock`.

---

## 6. A phase transition

```mermaid
sequenceDiagram
    participant S as Scheduler (every 30 s)
    participant GS as GameService
    participant FL as Core.transitions
    participant RE as Resolution
    participant DB as Database
    S->>S: now >= state.next_transition.at ?
    alt overdue by more than the catch-up limit
        S->>GS: mutate: paused = True + alert
    else
        S->>GS: mutate(snapshot="before night_lock (day 3)")
        GS->>FL: run_transition(state, NIGHT_LOCK, scheduled)
        FL->>FL: phase = SLEEP, close wolf vote
        FL->>RE: preview_night(deepcopy of state, stored seed)
        RE-->>FL: report
        FL->>FL: next_transition = next after the scheduled time
        GS->>DB: commit (state, snapshot, preview report)
    end
    Note over S,DB: 08:00 - MORNING
    S->>GS: mutate(snapshot="before morning (day 3)")
    GS->>FL: run_transition(MORNING)
    FL->>RE: resolve_night(real state, same seed)
    RE-->>FL: report (deaths applied, messages emitted)
    FL->>FL: day += 1, phase = DAY, expire conditions
    S->>S: final report != last preview? then alert the GMs
    GS->>DB: commit
```

- The next transition is computed from the **scheduled** time of the previous one. A bot that was offline for a
  short while runs the missed transitions in order. Beyond the catch-up limit (2 hours by default) the clock
  pauses, and a GM decides (`/gm clock resume`).
- The transition kinds and their order are in [Core/clock.py](../Core/clock.py): MORNING → NEWSPAPER → DUSK →
  (SECOND_LYNCH_END) → NIGHT_LOCK.
- What each transition does is in [Core/transitions.py](../Core/transitions.py) (`_morning`, `_newspaper`,
  `_dusk`, `_night_lock`); the lynch parts of dusk and the second lynch are in [Core/lynch.py](../Core/lynch.py).
- A transition that crashes is rolled back, and the clock pauses until a GM fixes it.

---

## 7. Effects and the outbox

The engine asks for side effects by emitting `Effect` dataclasses ([Core/effects.py](../Core/effects.py)):

| Effect | Delivered as |
|---|---|
| `PrivateMessage` | embed in the player's private channel (split if long) |
| `ChatMessage` | embed in a chat's channel |
| `Announcement`, `VoteResults`, `NewspaperPost` | the announcements channel |
| `RoleCard` | role card in the private channel |
| `DecisionPrompt` | select menu for the chooser (or in #mod-log for the GMs) |
| `QuestionPrompt` | yes/no buttons (dead chat, or a private channel for the Open Book) |
| `TelepathPrompt` | message with a Reply button |

Channels are not an effect: before delivering, the worker creates a Discord channel for every chat that
doesn't have one yet (chats made mid-game, like a merged coven chat, get theirs this way).

**Delivery.**
- `EffectDelivery` delivers outbox rows in order.
- A failure is retried (up to 5 attempts), and the GMs are alerted if it keeps failing.
- Because effects are saved with the state, a crash just means they're delivered after the restart.

**Persistent components.** Buttons and menus are `DynamicItem`s with the ids in their `custom_id`, for example
`xpw:question:<guild>:<question id>:yes`. `bot.add_dynamic_items(*DYNAMIC_ITEMS)` re-attaches them after a restart.
See [Services/views.py](../Services/views.py).

---

## 8. Channel access

Who may see or write where is **never stored**. It's derived from the state by `player_access(state, chat,
player)` in [Core/access.py](../Core/access.py), which returns `WRITE`, `READ`, `REACT` or `NONE`.

```mermaid
flowchart TD
    S{chat kind} -->|VILLAGE| V{player}
    V -->|alive| V1["WRITE (READ during lockdown)"]
    V -->|skeleton| V2[REACT]
    V -->|dead| V3[READ]
    S -->|DEAD chat| D{"dead, and not an<br/>active Vengeful Spirit?"}
    D -->|yes| D1[WRITE]
    D -->|no| D2["NONE (death rules)"]
    S -->|any other| M{membership}
    M -->|none / revoked| N[NONE]
    M -->|former, or chat archived| R[READ]
    M -->|active| K{kind and player}
    K -->|PRIVATE| K1["WRITE (also when dead)"]
    K -->|alive| K2["WRITE (READ during lockdown)"]
    K -->|skeleton| K3["WRITE in skeleton/undead chats, else READ"]
    K -->|dead| K4["WRITE in spirit chat, else READ"]
```

**The reconciler.** `ChannelManager.sync` compares this with each channel's current permission overwrites and
changes only what differs. It runs after every change and on startup, so manual edits in Discord get corrected.
Public Discord roles (Dead / Vengeful Spirit / Skeleton) follow `player.public_role`, which is updated at the
newspaper (or straight away for a lynch).

**Categories.** Channels are created in categories by kind: Important (announcements), General (village, dead
chat), Families, Factions, Roles (private channels), Game Masters (mod log). Existing categories with those
names are reused. Channels are never renamed.

---

## 9. Registries and extension points

| Registry | Where | Filled by |
|---|---|---|
| `ROLE_REGISTRY` / `MODIFIER_REGISTRY` | `Core/actor.py` | `@register_role` / `@register_modifier` |
| `FACTIONS` | `Core/factions.py` | `register_faction(Faction(...))`, with the win check (the Coven registers itself in `Roles/coven/_coven.py`) |
| `CHAT_DEFS` | `Core/players.py` | `register_chat(key, kind, channel_name)` |
| `CONVERSIONS` | `Core/resolution.py` | `register_conversion(kind, fn)` |
| `PREPARE_HOOKS` / `FINAL_HOOKS` | `Core/resolution.py` | `register_prepare_hook` / `register_final_hook` |
| `DECISION_HANDLERS` | `Core/decisions.py` | `DECISION_HANDLERS["kind"] = fn` (the lynch tiebreaks in `Core/lynch.py`) |
| `COMMAND_COGS` / `COMMAND_GROUPS` | `Services/role_commands.py` | subclassing `RoleCommands` |
| `DYNAMIC_ITEMS` | `Services/views.py` | the tuple at the end of the file |
| Polymorphic families (`actor`, `effect`) | `Core/serialize.py` | subclassing `Polymorphic` |

All of these are filled at import time. Importing `Roles` (which `bot.py` and the tests do) is enough.

---

## 10. Where to change what

| I want to... | Change |
|---|---|
| add or remove a role | a file in `Roles/<faction>/` (see the role guide) |
| add a game-wide night rule | a prepare or final hook in a `Roles/.../_something.py` module |
| add a faction | `register_faction` (in `Core/factions.py`, or in the faction's `Roles/` module like the Coven's in `_coven.py`) + roles with that `faction` |
| keep game-wide data for one role or faction | `state.data`, behind helpers in that role's module, keys prefixed with its name |
| keep game-wide data the engine itself needs | a typed field on `GameState` |
| add a transition or change the daily rhythm | `Core/clock.py` (`TransitionKind`, `allowed_next`) + a handler in `Core/transitions.py` |
| add a kind of message or Discord side effect | an `Effect` subclass in `Core/effects.py` + a branch in `EffectDelivery.apply` |
| add a GM tool | a command in `Cogs/gm.py` (watch the 25-subcommand limit; there's a `clock` subgroup) |
| change who sees which channel | `Core/access.py` |
| change the stored shape of the state | just change the dataclasses; finish or delete running games first if a field is renamed |
| add a database table | `SCHEMA` in `Storage/db.py` (`CREATE TABLE IF NOT EXISTS` runs on every start) |
| change the player guide | role descriptions/abilities, then `python tools/generate_docs.py` |
