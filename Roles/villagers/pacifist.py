from Roles.role import *


@register_role
class Pacifist(Role):
    name = "pacifist"
    display = "Pacifist"
    faction = VILLAGERS
    tags = frozenset({"villager_role"})
    description = (
        "Once per game you can stop the whole lynch vote: nobody is lynched that day. You learn the faction of the "
        "person who was about to be lynched. You can't stop the Ruthless Counselor's second lynch."
    )
    abilities = (
        Ability("stop", Timing.DAY, "Stop today's lynch: nobody will be lynched", priority=Priority.INFO, uses=1),
    )

    def resolve_stop(self, ctx: Resolution, action: SubmittedAction) -> None:
        ctx.flags["lynch_stopped"] = True
        ctx.note("Notes", "The Pacifist stops the lynch")
        target = ctx.flags.get("lynch_target")
        tally = ctx.flags.get("lynch_tally")
        if target is not None:
            player = ctx.state.player(target)
            ctx.inform(self.owner, f"You stopped the lynch of **{player.display_name}**, who belongs to the "
                                   f"**{faction_display(player.true_faction())}**.")
        elif tally is not None and tally.outcome == "tie":
            names = ", ".join(ctx.state.name(t) for t in tally.tied)
            ctx.inform(self.owner, f"You stopped the vote. It was a tie ({names}) - nobody in particular was about "
                                   "to be lynched.")
        else:
            ctx.inform(self.owner, "You stopped the vote, but nobody was about to be lynched.")


class PacifistCommands(RoleCommands, group_name="pacifist", source="pacifist"):
    @app_commands.command(name="stop", description="Stop today's lynch vote (once per game)")
    async def stop(self, interaction: discord.Interaction) -> None:
        await self.use(interaction, "stop")

    @app_commands.command(name="cancel", description="Let the vote go on after all")
    async def cancel_stop(self, interaction: discord.Interaction) -> None:
        await self.cancel(interaction, "stop")
