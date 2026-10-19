from Roles.role import *


@register_role
class Werewolf(Role):
    """A werewolf without abilities. Nobody starts as this: it's what a wolf
    becomes when revived after the Apprentice wolf took over their role."""
    name = "werewolf"
    display = "Werewolf"
    faction = WEREWOLVES
    groups = ("wolves",)
    can_vote_wolf_kill = True
    assignable = False
    description = "You are a werewolf without special abilities. Help the pack choose who to eat."
