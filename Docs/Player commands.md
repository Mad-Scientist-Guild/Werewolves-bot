# XP Werewolves - commands

_Generated from the bot's role definitions (`python tools/generate_docs.py`)._

## Commands for everyone

| Command | What it does |
|---|---|
| `/game join` | Join the game before it starts |
| `/game players` | Who's playing and what is publicly known about them |
| `/game status` | Current phase, day and what happens next |
| `/me` | Your role, what you can do right now and your pending actions |
| `/role_info <role>` | Read the description of any role |
| `/rules` | The general rules |
| `/lynch vote <player>` | Vote to lynch someone (from 12:00 until 19:00; change your vote any time) |
| `/lynch abstain` · `/lynch retract` · `/lynch my_vote` | Abstain, take back your vote, see your vote |
| `/mayor vote <player>` | Vote in the mayor election (day 1) |
| `/mayor successor <player>` | (Mayor) choose who takes over if you die |
| `/mayor who` | Who is the Mayor? |

Night actions can be submitted from 19:00 until 00:00 and are locked in after that; you can change them
with the same command until the lock. Day actions can be used from 08:00 until 19:00. Your results arrive
in your private channel. Every command answers only you - nobody else sees that you used it.

## Villagers

### Actor
*Villagers*

Once per day you can take on another villager role: for that day and the following night you have its powers (with fresh uses) and can use its commands. You can never take on the same role twice, and not the Adopted Child, a Brother, the Grave Robber or Cupid. A copied Spiritualist doesn't get the Vengeful Spirit's chat, a copied Monster Hunter has no silver.

**Commands:**
- `/actor copy <role>` — Take on another villager role for today and tonight *(instant)*

### Adopted Child
*Villagers*

You have access to one extra family chat, without being publicly known as part of that family. That family is told who you are. You can join your second family at any time - **ask the GMs in your private channel** when you want to.

_No commands of your own._

### Brother
*Villagers*

The bond of Brothers transcends family. All Brothers share a private chat, so you know each other's role and can plan together. At any time the Brothers can unanimously add someone else to the chat - their role isn't revealed to you. Every living Brother has to propose the same person with `/brother invite`.

**Commands:**
- `/brother invite <target>` — Propose adding someone to the Brothers' chat (every Brother must agree) *(instant)*

### Fox
*Villagers*

Once a night you can point at three people. If at least one of them is not a Villager, you're told so. If all three are Villagers, you're told that too - and you lose your ability for the rest of the game.

**Commands:**
- `/fox sniff <first> <second> <third>` — Point at three players: learn whether any of them is not a villager *(night action)*

### Gambler
*Villagers*

Once a night you can visit a player and learn their full role. But if they belong to an evil faction (Werewolves, Undead or Coven) you die tragically. Visiting the Lich kills you and turns you into a Skeleton.

**Commands:**
- `/gambler visit <target>` — Visit a player and learn their role - deadly if they're evil *(night action)*

### Grave Robber
*Villagers*

Once per game you can plunder the grave of a dead player. You learn their role and take it over - with fresh uses of its powers - and from then on you belong to that role's faction. Plundering during the day gives you the role at 19:00 (in time for its night action); plundering at night gives it at 08:00 (in time for its day action). You can't plunder the grave of a Skeleton.

**Commands:**
- `/grave_robber rob <target>` — Plunder a dead player's grave and take over their role *(any time, 1× per game)*

### Insomniac
*Villagers*

During the day you choose what you'll lie awake listening for tonight: how many of your family members leave the house, or how many people visit your family (any number of werewolves sounds like one wolf). If the Village Slut visits you, you learn each other's roles.

**Commands:**
- `/insomniac listen <mode>` — Choose what you'll listen for tonight *(day action)*

### Locksmith
*Villagers*

Once a night you can lock someone's house (a house is a whole family; your own is allowed). Nobody can enter a locked house - not Villagers, Werewolves, Undead or Coven - and nobody inside can use powers that make them leave the house. You can never lock the same person's house twice.

**Commands:**
- `/locksmith lock <target>` — Lock a player's house (their whole family) for the night *(night action)*

### Monster Hunter
*Villagers*

First you need to find the Silver Angel: once a night, point at a player to check whether they are the Silver Angel. Once you've found them you have silver, and every night you can point at a player and kill them if they belong to an evil faction. Armed with silver, a Shadow wolf stalking you dies when you go out.

**Commands:**
- `/monster_hunter search <target>` — Check whether a player is the Silver Angel *(night action)*
- `/monster_hunter hunt <target>` — Kill a player if they belong to an evil faction *(night action)*

### Old Hunter
*Villagers*

Once a night you can coat your sword in wolfsbane (your stash lasts 3 nights). If werewolves attack you - or try to turn you - while your sword is coated, you survive and one of the attacking wolves dies the next morning. If they attack while it isn't coated, you die. You can only kill werewolves this way. (Coating doesn't make you leave the house, so wolves who only track or stalk you are safe.)

**Commands:**
- `/old_hunter coat` — Coat your sword in wolfsbane tonight *(night action, 3× per game)*

### Pacifist
*Villagers*

Once per game you can stop the whole lynch vote: nobody is lynched that day. You learn the faction of the person who was about to be lynched. You can't stop the Ruthless Counselor's second lynch.

**Commands:**
- `/pacifist stop` — Stop today's lynch: nobody will be lynched *(day action, 1× per game)*

### Peeking Girl
*Villagers*

Once per day (midnight to midnight) you can pick a 60-minute window to listen in on the werewolves. From the moment a wolf talks during that window, you get the first 15 minutes of their chat as a transcript - speakers are numbered (the same number for the same wolf every time), names they mention stay visible. The time must be in the future. Spying counts as leaving your house that night.

**Commands:**
- `/peeking_girl peek <start>` — Listen in on the werewolf chat for an hour *(instant)*

### Priest
*Villagers*

Twice per game you can bless a family during the day: nobody in that family can die during the coming night - except a lover dying of a broken heart. (Being turned isn't dying, so a blessing doesn't stop it.)

**Commands:**
- `/priest bless <member>` — Bless a family: nobody in it can die tonight *(day action, 2× per game)*

### Prophet
*Villagers*

Every night you can pray for a role. If a living player has it, you receive a list of a third of the living players, at least one of whom has that role. If nobody alive has it, you're told so.

**Commands:**
- `/prophet pray <role>` — Pray for a role *(night action)*

### Ruthless Counselor
*Villagers*

Twice per game - never two days in a row - you can call a second lynch right after the first one. All discussion and faction channels go into lockdown (private channels excepted) until its result is posted. Everyone votes again until 20:00: abstaining isn't possible, someone will die, and on a tie you decide. The Pacifist can't stop it.

**Commands:**
- `/ruthless_counselor second_lynch` — Call a second lynch right after today's lynch *(day action, 2× per game)*

### Seer
*Villagers*

Each night, choose one person and learn their faction (Werewolves, Undead, Coven, Lovers or Villagers). If you choose someone you've looked into before, you learn their exact role instead.

**Commands:**
- `/seer check <target>` — Learn a player's faction (or their role, if you've checked them before) *(night action)*

### Silver Angel
*Villagers*

Every night you may protect one person (yourself included). They can't die that night from the Werewolves, the Coven or the Undead, and your protection also stops them from being turned. You can't protect the same person two nights in a row. The Monster Hunter is looking for you.

**Commands:**
- `/silver_angel protect <target>` — Protect a player tonight *(night action)*

### Spiritualist
*Villagers*

You can talk to the dead. Once a day you can ask them a yes-or-no question; you get the answer when all of them have responded, or at the end of the day (19:00) or night (00:00), whichever comes first. You learn how many said yes and no, not who. The dead may not lie. You can also talk with the Vengeful Spirit in a private chat.

**Commands:**
- `/spiritualist ask <question>` — Ask the dead a yes/no question (once a day) *(instant)*

### Telepath
*Villagers*

Once a day (08:00-00:00) you can send an anonymous message of at most 20 words to a living player. They receive exactly your message through a Game Master and can send one reply (also 20 words at most).

**Commands:**
- `/telepath send <target> <message>` — Send an anonymous message (max 20 words) to a living player *(instant)*

### Trapmaker
*Villagers*

Once a night you can set a trap at one person (yourself included) - the trap is on that person, not on their whole house. If anyone visits that person, one visitor (picked at random) is caught and you learn who it was; if the werewolves attack, a random wolf is caught. Their action still happens. The newspaper will mention that a trap went off, but not where.

**Commands:**
- `/trapmaker trap <target>` — Set a trap at a player tonight *(night action)*

### Undertaker
*Villagers*

Once a day you can examine one dead player: you learn what their role was and what role their killer had. If the werewolves killed them as a pack, you only learn that it was the werewolves.

**Commands:**
- `/undertaker examine <target>` — Examine a dead player: their role and their killer's role *(instant)*

### Vigilante
*Villagers*

Once a night you can pick another player to kill. If you kill a Villager (the Cultist counts as one), you die of guilt the same night. A Shadow wolf waiting outside your house dies, and you still go on to kill your target.

**Commands:**
- `/vigilante shoot <target>` — Kill a player tonight - if they're a villager, you die of guilt *(night action)*

### Village Slut
*Villagers*

Every night you can spend the night at someone else's house. If anyone attacks you at home, you're not there and survive. But if your host is attacked, you die with them - and if your host is turned into a werewolf or vampire, you're turned too. You learn whether your host left the house that night, and if you visit the Insomniac you learn each other's roles.

**Commands:**
- `/village_slut visit <target>` — Spend the night at someone else's house *(night action)*

### Villager
*Villagers*

You have no special abilities. Use your wits, your vote and your voice to find the evil among you.

_No commands of your own._

### Wanderer
*Villagers*

At night you wander through town and spot someone who left their house, picked at random - they don't know you saw them. After the first night you can also choose to look for the same person again: you'll learn whether they went out again.

**Commands:**
- `/wanderer wander [mode]` — Wander the town tonight *(night action)*

### Witch
*Villagers*

You have two potions, each usable once. The **potion of death** (at night) kills a player by the next morning. The **elixir of life** (during the day) brings back someone who died last night - they return after the lynch. Using a potion means leaving your house. A Village Slut visiting your victim dies with them; if the Slut is your victim but isn't home, nothing happens and you keep the potion.

**Commands:**
- `/witch poison <target>` — Use your potion of death on a player *(night action, 1× per game)*
- `/witch revive <target>` — Use your elixir of life on someone who died last night *(day action, 1× per game)*

## Werewolves

### Ancient wolf
*Werewolves*

Once per game you can spare the werewolves' victim and turn them into a werewolf instead: they join the Werewolf faction and the werewolf chat, keeping their own abilities. Only you leave the house that night. If the turn fails you keep your ability.

**Commands:**
- `/ancient_wolf turn` — Turn tonight's werewolf victim into a werewolf instead of killing them *(night action, 1× per game)*

**Werewolf pack (every werewolf):** `/wolves vote <player>` · `/wolves abstain` · `/wolves status` - the pack eats
someone only if more than half of the pack votes for them; not voting counts as abstaining.

### Apprentice wolf
*Werewolves*

The night after a fellow wolf dies, you can take up their role - only that night, or the chance is gone. You then become that wolf, with whatever charges they had left, and lose your apprentice ability. If that wolf is ever revived, they come back as a wolf without abilities.

**Commands:**
- `/apprentice_wolf take_over <target>` — Take over the role of a wolf who just died *(night action)*

**Werewolf pack (every werewolf):** `/wolves vote <player>` · `/wolves abstain` · `/wolves status` - the pack eats
someone only if more than half of the pack votes for them; not voting counts as abstaining.

### Bloodhound
*Werewolves*

Once a night you can follow one person's scent: you'll learn whether they left their house that night (also if they tried and were stopped). You leave your own house to do this.

**Commands:**
- `/bloodhound track <target>` — Find out whether a player leaves their house tonight *(night action)*

**Werewolf pack (every werewolf):** `/wolves vote <player>` · `/wolves abstain` · `/wolves status` - the pack eats
someone only if more than half of the pack votes for them; not voting counts as abstaining.

### Cultist
*Werewolves*

You are a villager who serves the Werewolves. You're in the werewolf chat but can't vote on who to eat. Investigations see you as a Villager, and the Monster Hunter can't kill you. If you are the last one left of the Werewolf faction, you lose.

_No commands of your own._

### Cunning wolf
*Werewolves*

When you vote in the lynch you can name a second player: when the votes are published, that name is listed as your vote instead of the player you really voted for. Your real vote is what counts. (A normal `/lynch vote` works too.)

**Commands:**
- `/cunning_wolf vote <target> <shown_as>` — Vote in the lynch, with a different name shown when the votes are published *(instant)*

**Werewolf pack (every werewolf):** `/wolves vote <player>` · `/wolves abstain` · `/wolves status` - the pack eats
someone only if more than half of the pack votes for them; not voting counts as abstaining.

### Feral wolf
*Werewolves*

Three times per game you can, on top of the pack's kill, go out alone and eat another player - of any faction, werewolves included. You leave your house to do this.

**Commands:**
- `/feral_wolf eat <target>` — Eat an extra player tonight, on your own *(night action, 3× per game)*

**Werewolf pack (every werewolf):** `/wolves vote <player>` · `/wolves abstain` · `/wolves status` - the pack eats
someone only if more than half of the pack votes for them; not voting counts as abstaining.

### Normal wolf
*Werewolves*

You have no extra powers, but you have inside information: you know one villager role that is not in the game. Share it with the other wolves or keep it to yourself.

**Werewolf pack (every werewolf):** `/wolves vote <player>` · `/wolves abstain` · `/wolves status` - the pack eats
someone only if more than half of the pack votes for them; not voting counts as abstaining.

### Rabid wolf
*Werewolves*

Once per game you can go on a killing spree: name a living player and guess their role. A correct guess kills them (unless they're protected) and you may go on with another player; a wrong guess ends the spree. If you pick the Vigilante or a Monster Hunter armed with silver, you die in an epic battle.
**This role is resolved by the GMs:** tell them your spree in your private channel during the night.

**Werewolf pack (every werewolf):** `/wolves vote <player>` · `/wolves abstain` · `/wolves status` - the pack eats
someone only if more than half of the pack votes for them; not voting counts as abstaining.

### Shadow wolf
*Werewolves*

Once a night you can stalk a player. If they leave their house, you are waiting for them: they're forced back and their night action fails (limited uses aren't lost). They'll know the Shadow wolf visited. You can never stalk the same player twice. Beware: a Vigilante going out to kill, or a Monster Hunter armed with silver, kills you instead - and still goes on with their action.

**Commands:**
- `/shadow_wolf stalk <target>` — Wait outside a player's house tonight *(night action)*

**Werewolf pack (every werewolf):** `/wolves vote <player>` · `/wolves abstain` · `/wolves status` - the pack eats
someone only if more than half of the pack votes for them; not voting counts as abstaining.

## Undead

### Lich
*Undead*

You must raise an army to take over the town. Once a night you can pick two different dead players and guess their roles: everyone you guess right rises as your Skeleton and joins your private chat. You can only die by lynching - but when you die, all your skeletons die with you.

**Commands:**
- `/lich raise <first> <first_role> [second] [second_role]` — Guess the roles of up to two dead players - correct guesses rise as Skeletons *(night action)*

### Vampire Lord
*Undead*

Every night you can bite a player to kill them. While you have no Vampire Spawn you may instead turn your victim into one: they join the Undead (and your chat) the next morning, keeping their own abilities. Turning only works if you're still alive. If you and the Ancient wolf turn the same person, one fails.

**Commands:**
- `/vampire_lord bite <target> [mode]` — Bite a player tonight - kill them, or turn them into your Spawn *(night action)*

## Coven

### Curseweaver
*Coven*

Each night you can curse someone (never the same person twice in a row):
• **Curse of the Puppet** - their night ability hits someone else, picked at random from the living (Coven members you know are left out).
• **Curse of Transformation** - they're turned into a lizard and can't perform their night action.
Werewolves only lose their own ability, not the pack's vote. The victim learns they were cursed the next morning. Like every Coven member you can also try to find your fellow members.

**Commands:**
- `/curseweaver find <target>` — Guess a fellow Coven member - if you're right, you join forces *(night action)*
- `/curseweaver curse <target> <curse>` — Curse a player tonight *(night action)*
- `/curseweaver kill_list` - see the Coven's kill list once you've found a fellow member

### Diviner
*Coven*

Each night you can divine a house (a family) in one of three ways:
• **Detection** - learn one person who left that house during the night.
• **Vision** - learn one role living in that house.
• **Scrying** - pick a 60-minute window (in the future) to listen in on that family's chat: you get the first 15 minutes of conversation from the moment someone talks, speakers numbered, names they mention visible.
Coven members you know are never picked for Detection or Vision. Like every Coven member you can also try to find your fellow members.

**Commands:**
- `/diviner find <target>` — Guess a fellow Coven member - if you're right, you join forces *(night action)*
- `/diviner divine <target> <method>` — Divine a house tonight: Detection or Vision *(night action)*
- `/diviner scry <target> <start>` — Listen in on a house's family chat for an hour (instead of divining tonight) *(instant)*
- `/diviner kill_list` - see the Coven's kill list once you've found a fellow member

### Enchantress
*Coven*

Once per day you can enchant another player with one charm (it wears off the next morning; they're told they were enchanted):
• **Open Book** - they must honestly answer a yes/no question (not about their role, ability or faction).
• **Protection** - they can't be killed during the coming night (doesn't stop turning). Never twice on the same person.
• **Revenge** - if they're killed during the night, the next day between 08:00 and 18:00 you may kill one player. After that you can no longer use the Charm of Protection.
Like every Coven member you can also try to find your fellow members.

**Commands:**
- `/enchantress find <target>` — Guess a fellow Coven member - if you're right, you join forces *(night action)*
- `/enchantress enchant <target> <charm> [question]` — Enchant a player with one of your charms (once per day) *(instant)*
- `/enchantress revenge <target>` — Unleash your revenge: kill a player *(instant)*
- `/enchantress kill_list` - see the Coven's kill list once you've found a fellow member

### Hag Mother
*Coven*

Once per game you can secretly pick someone in the village to be your Changeling - they don't know it. After 3 nights they grow up into a hag hybrid: they join the Coven (and your Coven group), keeping their own role and chats. If you die before that, they never grow up.
With your motherly instinct you can search for three fellow Coven members each night instead of one. Once the whole Coven has found each other, you can check whether a role on the kill list is still alive.

**Commands:**
- `/hag_mother find <target> [target2] [target3]` — Search for up to three fellow Coven members *(night action)*
- `/hag_mother changeling <target>` — Secretly make someone your Changeling (once per game) *(night action, 1× per game)*
- `/hag_mother check <role>` — Check whether a role on the kill list is still alive *(night action)*
- `/hag_mother kill_list` - see the Coven's kill list once you've found a fellow member

## Lovers

### Cupid
*Lovers*

On the first night you link two people (you may pick yourself): they fall in love, share a chat, and die of a broken heart if the other dies. You and the lovers win if the lovers (and maybe you) are alive at the end. While both lovers live, you can't die from a lynch - the village learns you're Cupid instead. Once a lover dies, you join the Villagers.

**Commands:**
- `/cupid link <first> <second>` — Make two players fall in love (first night only) *(night action, 1× per game)*

## Acquired during the game

These can't be dealt out at the start - they happen to you during the game.

### Changeling

You've grown up into a hag hybrid! You keep your role, its abilities and your chats, but you now win with the Coven. You've found the Hag Mother: you share her Coven group.

### Lover

Cupid's arrow struck you. You and your lover share a chat and want to survive together, whoever else wins. If your lover dies, you die of a broken heart.

### Skeleton

You've been raised from the dead to serve the Lich. You're back in the village chat, but you may only react (default and Werewolves emotes only - and don't spell words with letters!). You can't vote, and you can no longer see the dead chat, though you may share what you learned there. You share a chat with the Lich and the other skeletons. If the Lich dies, so do you - and a Skeleton never rises again.

### Turned wolf

You have been turned into a werewolf! You keep your role, its abilities and every chat you had, but you now win with the Werewolves. You've joined the werewolf chat and help choose who to eat.

### Vampire Spawn

The Vampire Lord turned you into a Vampire Spawn. You keep your role, its abilities and your chats, but you now win with the Undead and share their chat. Every kill the Vampire Lord makes counts for you too: if the Lord dies after you've shared in a kill, you become the new Vampire Lord.

### Vengeful Spirit

Dying first is just bad - and it made you angry. You can talk with the Spiritualist in a private chat (not with the other dead). Within three nights you may name who - or what - killed you, once: if you're right, they die. Killed by the werewolf pack? Any werewolf will do. Either way, after your guess or the three nights you move on to the afterlife.

**Commands:**
- `/vengeful_spirit avenge <target>` — Name who killed you - if you're right, they die *(night action, 1× per game)*

### Werewolf

You are a werewolf without special abilities. Help the pack choose who to eat.
