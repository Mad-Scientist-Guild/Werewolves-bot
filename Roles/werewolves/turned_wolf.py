from Core.resolution import register_conversion
from Roles.role import *


@register_modifier
class TurnedWolf(Modifier):
    """Acquired, never assigned: a player turned by the Ancient wolf. They keep
    their role, abilities and chats, but now win with the Werewolves - also
    if they are revived later."""
    name = "turned_wolf"
    display = "Turned wolf"
    description = (
        "You have been turned into a werewolf! You keep your role, its abilities and every chat you had, "
        "but you now win with the Werewolves. You've joined the werewolf chat and help choose who to eat."
    )
    true_faction = WEREWOLVES
    can_vote_wolf_kill = True
    groups = ("wolves",)

    turned_by: int | None = None
    turned_day: int = 0


def turn_into_wolf(ctx: Resolution, target: int, by: int) -> None:
    """The "werewolf" conversion. Use ctx.convert("werewolf", target, by=...) so
    other actors (the visiting Village Slut) are told about it."""
    player = ctx.state.player(target)
    add_modifier(ctx.state, player, "turned_wolf", reason=f"turned by {ctx.state.name(by)}",
                 turned_by=by, turned_day=ctx.state.day)
    ctx.inform(target, "You were attacked by the werewolves... and survived as one of them. You are now a "
                       "**Turned wolf**: you keep your role but win with the Werewolves, and you've joined their chat. "
                       "Vote on the pack's victim with `/wolves vote`.")


register_conversion("werewolf", turn_into_wolf)
