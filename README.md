# Werewolves-bot

A Discord bot that runs the online **XP Werewolves** event: a heavily modified *Werewolves of Millers Hollow* played
in real time. Days and nights are real days and nights. The rules are in [`Docs/`](Docs/).

- **Nothing is lost on a crash.** All game state lives in SQLite and is saved after every change. On restart the
  bot reloads every game, delivers anything still queued, re-syncs channel permissions and catches up on missed
  transitions.
- **Everything is logged.** Every action, vote, transition, death and permission change goes to the `events`
  table and to the GM `#mod-log` channel, as do commands that were rejected or crashed. Things that need a GM
  ping the GM role.
- **Nights are previewed.** At 00:00 the bot resolves the night and posts a full report for the GMs. GMs can still
  adjust things, and the final result is applied at 08:00.

## Running it

```bash
python -m venv env
env\Scripts\activate          # Windows; use `source env/bin/activate` elsewhere
pip install -r requirements.txt
copy .env.example .env        # then fill in DISCORD_TOKEN (and GUILD_ID while developing)
python bot.py
```

Tests: `python -m pytest`

**Discord application settings.**
- Privileged intents: enable *Server Members* and *Message Content*.
- Invite scopes: `bot` and `applications.commands`.
- Permissions: Manage Channels, Manage Roles, View Channels, Send Messages, Embed Links, Attach Files, Read Message
  History, Add Reactions.
- Place the bot's role **above** the Dead / Vengeful Spirit / Skeleton roles.

`.env` options: `DISCORD_TOKEN`, `GUILD_ID` (development guild for instant command sync), `ENV`
(`development`/`production`), `DB_PATH`, `LOG_DIR`, `TIMEZONE`, `GM_ROLE_ID`.

## GM quick start

1. `/game create`: creates `#announcements` (also where vote results are posted), `#mod-log` and the Dead /
   Vengeful Spirit / Skeleton roles. Pass existing channels if you already have them. Game channels are sorted into the categories
   Important, General, Families, Factions, Roles and Game Masters (existing categories with those names are reused).
2. Players `/game join` (or `/setup add_player`). Waiting-list players: `/setup backup add`.
3. The role pool starts with the default setup: one of every role, three Brothers. Adjust it with
   `/setup roles_add` / `/setup roles_remove` until it matches the player count (`/setup roles` shows it,
   `/setup roles_default` resets it).
4. `/setup families [size]` (move people with `/setup family_move`).
5. `/setup assign preview`, then `/setup assign apply`.
6. Optional: `/setup times`, `/setup timezone`, `/setup gm_role`, `/setup role_setting` (e.g. extra uses).
7. `/setup channels` to create the channels now (otherwise `/game start` does it), then `/game start`.

**Every day** (times are configurable):

| Time  | What happens |
|-------|--------------|
| 08:00 | The night is applied. Players get their info. The night's dead are muted and moved to the dead chat **quietly**. |
| 12:00 | The newspaper image (`/gm newspaper`) is posted, public Dead/Skeleton/Vengeful Spirit roles are given out, and the lynch opens. |
| 19:00 | The lynch closes and the full vote list is published. Day actions resolve and the night begins. |
| 20:00 | Only if the Ruthless Counselor called a second lynch. |
| 00:00 | Night actions lock. The **preview report** is posted in `#mod-log`. |

**During the night** you can:
- check things with `/gm actions` and `/gm preview`;
- fix things with `/gm act` (enter an action for a player, also during sleep time), `/gm cancel_action` and
  `/gm override kill|spare`.

Every change re-runs the preview. If the 08:00 result differs from the last preview, you get an alert.

**Other tools:**
- `/gm status` and `/gm player` (everything about a player)
- `/gm log` (search the audit log)
- `/gm kill` / `/gm revive` / `/gm replace` (the Reaper)
- `/gm set_role` / `/gm modifier` / `/gm group`
- `/gm decide` (make a pending choice for someone)
- `/gm clock pause|resume|advance|snapshots|rollback`
- `/gm end_game` (works before the start too; everything is kept until `/game delete`, which asks for
  confirmation and can also remove the bot-made channels)

A snapshot is taken before every transition, so `/gm clock rollback` can undo one. Discord messages that were
already sent stay.

## Design rules

These come from the GMs and are enforced in code:

- **Channels are never renamed** during a game. When a role changes, the player is told in their private channel.
- **No data is made inaccessible.** The bot never deletes or edits messages or channels. Leaving a chat makes it
  read-only. The only full revocations are the death rules: the dead chat is for the dead only, Skeletons and
  revived players leave it, and the Vengeful Spirit is kept out of it.
- **Simultaneous actions read the state from before that moment.** A Seer still sees "Villager" for someone turned
  the same night.
- **Quiet deaths.** Night deaths are handled at 08:00 without a public announcement. The public Discord role follows
  at the 12:00 newspaper. Only Dead, Vengeful Spirit and Skeleton have a Discord role.
- **Votes.**
  - Werewolves need a majority of the eligible pack; not voting counts as abstaining.
  - A lynch tie goes to the Mayor's vote if the Mayor voted for one of the tied players; otherwise the Mayor picks.
  - On the second lynch, the Ruthless Counselor always picks.
  - If more than half of the voters don't vote or abstain, nobody is lynched.

## Architecture

```
bot.py          startup, central error handling, automatic command logging
Core/           the game engine - pure Python, no Discord, fully unit-tested
  state.py        GameState / Player / Group (IDs only, serialisable)
  actor.py        Role / Modifier base classes and registries
  abilities.py    Ability / Param declarations
  actions.py      submitting and validating actions
  resolution.py   the resolution pipeline (night, dusk, instant)
  flow.py         setup, daily transitions, decisions, GM operations
  voting.py       lynch / second lynch / mayor / werewolf ballots
  access.py       who may see/write which channel (derived from state)
  factions.py     factions and win checks
  clock.py        real-time schedule
Storage/        SQLite (games, snapshots, reports, events, outbox)
Services/       Discord glue: game service (lock + save), audit poster, channel reconciler,
                effect delivery, decision views, role-command base class
Cogs/           slash commands: /game /setup /gm /lynch /mayor /me, scheduler, activity
Roles/          one file per role, by faction - auto-discovered
tests/          pytest scenarios (tests/builder.py makes them one-liners)
```

**How a change flows:** a command opens `runtime.games.mutate(guild_id)`, changes the state, and on exit the state
is saved in **one transaction** together with its log entries, *effects* (messages to send) and reports. If anything
fails, the state is restored. A background worker then delivers the effects and reconciles channel permissions from
the state.

**Resolution pipeline:** prepare hooks (e.g. the wolf pack's attack), then curses, then movement (who leaves the
house), then locks / stalks / protections, then evaluation of every action against the unchanged state, then a commit
pass that applies kills, conversions and the death cascade. See the docstring of `Core/resolution.py`.

## Adding (or removing) a role

Create one file under `Roles/<faction>/`. That's all. Delete the file to remove the role; a running game that still
has it keeps its data. [`Roles/villagers/silver_angel.py`](Roles/villagers/silver_angel.py) is a commented example:

```python
from Roles.role import *

@register_role
class Seer(Role):
    name = "seer"; display = "Seer"; faction = VILLAGERS
    description = "Each night, learn the faction of one player..."
    abilities = (Ability("check", Timing.NIGHT, "Learn a player's faction",
                         params=(P.living("target"),), priority=Priority.INFO),)
    checked: list[int] = field(default_factory=list)      # saved automatically

    def resolve_check(self, ctx: Resolution, action: SubmittedAction) -> None:
        target = ctx.target_of(action)
        ctx.inform(self.owner, f"{ctx.state.name(target)} is {ctx.apparent_faction(target, self.name)}")
        ctx.commit(lambda: self.checked.append(target))      # state changes only via commit

class SeerCommands(RoleCommands, group_name="seer", source="seer"):
    @app_commands.command(name="check", description="Learn a player's faction tonight")
    async def check(self, interaction: discord.Interaction, target: discord.Member):
        await self.use(interaction, "check", target=target)
```

`self.use()` handles everything: phase and sleep-time checks, uses, target validation, saving, logging and the
reply. Commands are tied to the *ability*, not the role, so a Grave Robber who took the Seer role (or anyone
copying it) can use `/seer check` too.

Hooks a role can implement: `validate`, `interact_<ability>`, `resolve_<ability>`, `on_visited`,
`protects_against`, `on_death`, `on_other_death`, `after_resolution`, `on_game_start`, `apparent_faction`,
`apparent_role`, `available_abilities`. Shared chats come from `groups = ("wolves",)`. Numbers like uses can be
overridden per game by GMs (`/setup role_setting <role> uses.<ability> <n>`).

Test a role with `tests/builder.py`:

```python
g = GameBuilder(); g.players(seer="seer", w1="ancient_wolf", w2="ancient_wolf", v="villager")
g.start(); g.dusk(); g.act("seer", "check", target="w1"); g.night()
assert "werewolves" in g.messages_for("seer")[0].lower()
```

## Status

All roles from the rules document are implemented, each with tests for its special interactions
(`python -m pytest`). Three rules are deliberately left to the GMs for now (see the GM manual):
- the **Rabid wolf**'s killing spree;
- the **Adopted Child**'s second family;
- whether protection can save the **Gambler** (the bot alerts the GMs when it happens).

Documentation:
- [`Docs/GM manual.md`](Docs/GM%20manual.md) - running a game.
- [`Docs/Developer guide - adding a role.md`](Docs/Developer%20guide%20-%20adding%20a%20role.md) - writing a role:
  requirements, the resolution pipeline, every hook and helper, a worked example.
- [`Docs/Developer guide - architecture and data.md`](Docs/Developer%20guide%20-%20architecture%20and%20data.md) -
  layers, the state dataclasses, serialisation, the database and the life of a change, with diagrams.
- [`Docs/Player commands.md`](Docs/Player%20commands.md) - the player guide. It's generated, so run
  `python tools/generate_docs.py` after changing roles.
