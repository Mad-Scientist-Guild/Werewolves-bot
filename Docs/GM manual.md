# XP Werewolves — GM manual

This is how to run a game with the bot. The player guide is generated separately: run
`python tools/generate_docs.py`, which writes `Docs/Player commands.md`.

## 1. Before the game

1. **`/game create`.** This creates `#announcements` and `#mod-log`, plus the Dead, Vengeful Spirit and Skeleton
   roles. Players vote in their private channels; vote results are posted in `#announcements`. Channels are
   sorted into the categories Important (announcements), General (village and
   dead chat), Families, Factions (wolves, undead, coven, lovers, brothers, spirit chats), Roles (private
   channels) and Game Masters (mod log). Existing categories with those names are reused; a category that
   reaches Discord's 50-channel limit gets an overflow ("Roles 2"). Set your GM role with `/setup gm_role` so the bot can ping you and give
   you access to every game channel.
2. **Players join** with `/game join`. GMs can add someone with `/setup add_player`. Put waiting-list players on
   the Reaper's list with `/setup backup add`.
3. **Role pool.** A new game starts with the default setup: one of every role and three Brothers. Adjust it with
   `/setup roles_add` / `/setup roles_remove` until `/setup roles` shows as many roles as players;
   `/setup roles_default` resets it. A plain *Villager* exists as filler but isn't in the default.
4. **Families (houses).** Run `/setup families [size]`, then move people with `/setup family_move`. A family is a
   house: Locksmith locks, Priest blessings, the Insomniac and the Diviner all work per family.
5. **Assign roles.** Run `/setup assign preview` and check the list. Apply it with `/setup assign apply`.
   - Change roles *before* creating channels: private channels are named after the starting role and are never
     renamed.
6. **Optional settings:**
   - `/setup times` and `/setup timezone`.
   - `/setup role_setting <role> <key> <value>` changes a role's numbers. Examples:
     - `uses.eat 4` gives the Feral wolf a fourth kill.
     - `hint seer` fixes the Normal wolf's hint.
     - `changeling_nights 2` makes the Changeling grow up after two nights.
     - `nights 3` sets the Vengeful Spirit's number of nights.
7. **`/setup channels`** creates every channel now, so you can look around. If you skip it, `/game start` does it.
8. **`/game start`.** Day 1 begins: role cards are posted in the private channels, the mayor election opens, and
   the Normal wolf hint and the Coven kill list are generated. Check the kill list with `/gm kill_list` and change
   it there if needed.

## 2. The daily cycle

The bot runs this on its own. Every transition takes a snapshot first.

| Time | The bot does |
|---|---|
| **08:00** | Applies the night. Players get their results in their private channels. The night's dead are muted and moved to the dead chat **without** a public announcement. |
| **12:00** | Posts the newspaper image you set with `/gm newspaper`, hands out the public Dead / Vengeful Spirit / Skeleton roles, and opens the lynch. |
| **19:00** | Closes the lynch and publishes all votes (Cunning wolf decoys applied). Applies the result, resolves the day actions (Grave Robber, Witch revive, Pacifist, Priest, Insomniac...) and opens the night and the wolves' vote. |
| **20:00** | Only when the Ruthless Counselor called a second lynch. Discussion channels are in lockdown until its result. |
| **00:00** | Night actions lock. The **night preview** is posted in `#mod-log`. |

If you forget the newspaper image at 12:00, you get an alert. The **Newspaper** section of each night report
lists what should go in it: traps that went off, Old Hunter kills, a new Mayor, and so on.

## 3. The night preview: your window to fix things

At 00:00 the bot resolves the night **as a preview**. Nothing is applied until 08:00. The report shows:

- every action
- who left their house
- what was blocked and why
- protections
- every kill attempt and its outcome
- deaths and cascades (heartbreak, skeletons...)
- what each player will be told
- newspaper notes
- a win check

Until 08:00 you can:

- `/gm act <player> <ability> ...` enters an action for a player. This also works during sleep time, for late
  requests in private channels.
- `/gm cancel_action <player> <ability>` cancels one.
- `/gm override kill <player> [cause]` or `/gm override spare <player>` forces or prevents a death tonight.
  `/gm override remove <player>` takes an override back.
- `/gm preview` re-runs the preview at any moment.

Every change during sleep time automatically posts an **updated preview**. At 08:00 the bot resolves the night
for real with the same random seed. If the result differs from the last preview, you get an alert.

## 4. Reading `#mod-log`

Everything that changes the game is logged:
- every action, vote, transition, death, conversion and permission change;
- commands that were rejected or crashed, with their arguments;
- every error.

Entries are batched into embeds. **⚠️ GM attention** messages ping the GM role. They're for:
- decisions waiting for someone;
- crashes;
- missed transitions;
- inactivity;
- win conditions;
- anything the rules leave to you.

`/gm log [player] [category] [count]` searches the log. `/gm status` and `/gm player` show the full state of the
game or of one player.

## 5. Decisions

Some choices wait for a player: the Mayor breaking a lynch tie, the Ruthless Counselor on a tied or empty second
lynch, or spawns choosing a new Vampire Lord (that one goes to you). The bot posts a select menu in the
chooser's private channel and alerts you. If someone doesn't answer, choose for them with
`/gm decide <id> <player>`. The id is in the alert and in `/gm status`.

## 6. When something goes wrong

- **The bot crashed or restarted.**
  - Nothing is lost.
  - On startup it reloads every game, delivers queued messages, re-syncs permissions and runs any missed
    transitions in order.
  - If it was down longer than the catch-up limit (2 hours by default), the clock pauses instead. Then:
    - `/gm clock resume` runs the missed transitions in order;
    - `/gm clock reschedule` skips ahead to the next upcoming one.
- **A transition crashed.** It's rolled back and the clock pauses. Fix the cause, then use `/gm clock advance`.
- **A mistake was applied.**
  - `/gm clock snapshots` lists the snapshots, and `/gm clock rollback <id>` restores one. The current state is
    snapshotted first, so a rollback can be undone.
  - Discord messages already sent stay. Correct them in public if needed.
- **Fix state by hand** with:
  - `/gm kill` (quiet by default; `public: True` for a public death)
  - `/gm revive`
  - `/gm set_role`
  - `/gm modifier add|remove`
  - `/gm set_faction`
  - `/gm group add|remove`
  - `/gm mayor set|open|close`
  - `/gm lockdown`
- **Testing in a dev server:** `/gm clock advance` runs the next transition immediately, so you can play a whole
  day in minutes.

## 7. Inactivity and the Reaper

The bot tracks activity from messages and commands.

- **Around 24 hours:** the player gets a warning in their private channel and you get an alert.
- **At 48 hours:** you get another alert.

The Reaper then has two options:
- `/gm replace <player> <backup>` moves the role, state, chats and pending actions to the new person, who gets the
  role card. The old account loses access.
- `/gm kill <player> inactive` kills them instead. GM kills never create a Vengeful Spirit.

## 8. Rules that are handled by GMs (for now)

- **Rabid wolf:** the killing spree isn't automated. The player tells you their spree; apply it with
  `/gm override kill` (at night) or `/gm kill`. Special cases:
  - a Vigilante, or a Monster Hunter armed with silver, kills the wolf;
  - a correct guess on a protected player ends the spree;
  - the Actor can always be guessed as "Actor".
- **Adopted Child:** add them to their second family with `/gm group add <player> family:<n>` and tell that
  family.
- **Gambler:** whether protection can save them from a tragic death isn't decided. The bot lets protection apply
  and alerts you whenever it did.

## 9. Channels and permissions

- Channels are **never renamed or deleted** during a game. When a player's role changes, they get a new role card
  in their private channel.
- **Nothing becomes unreadable:** leaving a chat (or a coven chat being merged) makes it read-only. The only real
  revocations are the death rules:
  - the dead chat is for the dead;
  - Skeletons and revived players leave it;
  - an active Vengeful Spirit is kept out of it and talks to the Spiritualist in their own spirit chat.
- Permissions follow the game state automatically. If someone fiddles with a channel by hand, the bot puts it back
  on the next change (or restart).
- The dead keep write access to their private channel (to talk to you). Skeletons can only react in the village
  chat. During the Ruthless Counselor's lockdown only private channels and the dead chat stay open.

## 10. Ending and deleting a game

- `/gm end_game <winner>` ends the game (also one that never started). The clock stops, but **everything is
  kept**: state, snapshots, reports, the audit log and all channels - also across restarts.
- `/game delete` removes the game and all its saved data for good, after you confirm with a button. With
  `delete_channels: True` it also deletes the channels and categories the bot created for the game (never
  channels you linked yourself or categories that already existed) and takes the Dead / Vengeful Spirit /
  Skeleton roles off the players.
- A new game can only be created once the previous one is deleted.
