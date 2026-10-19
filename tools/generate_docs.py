"""Generate the player command guide from the role declarations.

    python tools/generate_docs.py            -> writes Docs/Player commands.md

Run it again whenever roles change; the guide is built from each role's
description and abilities, so it can't drift from what the bot does.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import Roles  # noqa: E402,F401 - registers every role
from Core.actor import MODIFIER_REGISTRY, ROLE_REGISTRY  # noqa: E402
from Core.factions import COVEN, FACTIONS, faction_display  # noqa: E402
from Services.role_commands import COMMAND_GROUPS, ability_help  # noqa: E402

FACTION_ORDER = ["villagers", "werewolves", "undead", "coven", "lovers"]

EVERYONE = """\
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
"""

PACK = """\
**Werewolf pack (every werewolf):** `/wolves vote <player>` · `/wolves abstain` · `/wolves status` - the pack eats
someone only if more than half of the pack votes for them; not voting counts as abstaining."""

COVEN_EXTRA = "`/{group} kill_list` - see the Coven's kill list once you've found a fellow member"


def role_section(cls) -> str:
    lines = [f"### {cls.title()}", f"*{faction_display(cls.faction)}*", "", cls.description or "_No description._"]
    help_lines = ability_help(cls)
    if cls.faction == COVEN:
        help_lines.append(COVEN_EXTRA.format(group=COMMAND_GROUPS.get(cls.name, cls.name)))
    if help_lines:
        lines += ["", "**Commands:**"] + [f"- {line}" for line in help_lines]
    elif not cls.can_vote_wolf_kill:
        lines += ["", "_No commands of your own._"]
    if cls.can_vote_wolf_kill:
        lines += ["", PACK]
    return "\n".join(lines)


def build() -> str:
    parts = ["# XP Werewolves - commands", "",
             "_Generated from the bot's role definitions (`python tools/generate_docs.py`)._", "", EVERYONE]
    roles = [cls for cls in ROLE_REGISTRY.values() if cls.assignable]
    for faction in FACTION_ORDER + sorted(set(FACTIONS) - set(FACTION_ORDER)):
        members = sorted((c for c in roles if c.faction == faction), key=lambda c: c.title())
        if members:
            parts += [f"## {faction_display(faction)}", ""]
            parts += [role_section(cls) + "\n" for cls in members]
    parts += ["## Acquired during the game", "",
              "These can't be dealt out at the start - they happen to you during the game.", ""]
    acquired = sorted([c for c in ROLE_REGISTRY.values() if not c.assignable] + list(MODIFIER_REGISTRY.values()),
                      key=lambda c: c.title())
    for cls in acquired:
        text = [f"### {cls.title()}", "", cls.description or "_No description._"]
        if cls.abilities:
            text += ["", "**Commands:**"] + [f"- {line}" for line in ability_help(cls)]
        parts.append("\n".join(text) + "\n")
    return "\n".join(parts).rstrip() + "\n"


def main() -> None:
    target = ROOT / "Docs" / "Player commands.md"
    target.write_text(build(), encoding="utf-8")
    print(f"Wrote {target.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
