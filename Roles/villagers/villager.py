from Roles.role import *


@register_role
class Villager(Role):
    """Plain villager without abilities - useful as filler in the role pool."""
    name = "villager"
    display = "Villager"
    faction = VILLAGERS
    tags = frozenset({"villager_role"})
    description = "You have no special abilities. Use your wits, your vote and your voice to find the evil among you."
