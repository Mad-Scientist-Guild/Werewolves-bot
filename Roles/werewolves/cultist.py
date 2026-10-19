from Roles.role import *


@register_role
class Cultist(Role):
    name = "cultist"
    display = "Cultist"
    faction = WEREWOLVES
    groups = ("wolves",)
    description = (
        "You are a villager who serves the Werewolves. You're in the werewolf chat but can't vote on who to eat. "
        "Investigations see you as a Villager, and the Monster Hunter can't kill you. If you are the last one left "
        "of the Werewolf faction, you lose."
    )
    never_counts_for_faction = True   # doesn't keep the Werewolf faction alive on its own

    def apparent_faction(self, state: GameState, observer: str) -> str | None:
        return VILLAGERS
