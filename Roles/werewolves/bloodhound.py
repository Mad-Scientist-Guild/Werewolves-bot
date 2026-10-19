from Roles.role import *


@register_role
class Bloodhound(Role):
    name = "bloodhound"
    display = "Bloodhound"
    faction = WEREWOLVES
    groups = ("wolves",)
    can_vote_wolf_kill = True
    description = (
        "Once a night you can follow one person's scent: you'll learn whether they left their house that night "
        "(also if they tried and were stopped). You leave your own house to do this."
    )
    abilities = (
        Ability(
            "track", Timing.NIGHT, "Find out whether a player leaves their house tonight",
            params=(P.living("target", "Whose scent to follow"),),
            priority=Priority.INFO, leaves_house=True,
        ),
    )

    def resolve_track(self, ctx: Resolution, action: SubmittedAction) -> None:
        target = ctx.target_of(action)
        left = ctx.left_house(target)
        ctx.inform(self.owner, f"**{ctx.state.name(target)}** {'left their house' if left else 'stayed at home'} last night.")


class BloodhoundCommands(RoleCommands, group_name="bloodhound", source="bloodhound"):
    @app_commands.command(name="track", description="Find out whether a player leaves their house tonight")
    @app_commands.describe(target="Whose scent to follow")
    async def track(self, interaction: discord.Interaction, target: discord.Member) -> None:
        await self.use(interaction, "track", target=target)

    @app_commands.command(name="cancel", description="Cancel tonight's tracking")
    async def cancel_track(self, interaction: discord.Interaction) -> None:
        await self.cancel(interaction, "track")
