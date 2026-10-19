from Roles.role import *

# TODO(rabid wolf): automate the killing spree. Open design problem (GM decision, Oct 2026):
# each guess depends on the previous one ("if correct ... you can pick another living player"),
# but all night actions resolve together at the night lock, so a chained spree can't be resolved
# before the other night actions are known. Until that's decided the role is played by hand:
# the player tells the GMs in their private channel and the GMs apply the outcome
# (/gm override kill, or /gm kill), with the special cases from the rules document:
#   - target is the Vigilante or the Monster Hunter armed with silver -> the Rabid wolf dies
#   - correct guess but the target is protected -> nothing happens, the spree ends
#   - correct guess -> the target dies and the Rabid wolf may pick another living player
#   - wrong guess -> nothing happens, the spree ends
#   - the Actor can be guessed as "Actor" whatever they copied (but a copied Vigilante still kills the wolf)


@register_role
class RabidWolf(Role):
    name = "rabid_wolf"
    display = "Rabid wolf"
    faction = WEREWOLVES
    groups = ("wolves",)
    can_vote_wolf_kill = True
    description = (
        "Once per game you can go on a killing spree: name a living player and guess their role. A correct guess "
        "kills them (unless they're protected) and you may go on with another player; a wrong guess ends the spree. "
        "If you pick the Vigilante or a Monster Hunter armed with silver, you die in an epic battle.\n"
        "**This role is resolved by the GMs:** tell them your spree in your private channel during the night."
    )
