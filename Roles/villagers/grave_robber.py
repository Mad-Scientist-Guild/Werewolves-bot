from Roles.role import *


@register_role
class GraveRobber(Role):
    name = "grave_robber"
    display = "Grave Robber"
    faction = VILLAGERS
    description = (
        "Once per game you can plunder the grave of a dead player. You learn their role and take it over - with "
        "fresh uses of its powers - and from then on you belong to that role's faction. Plundering during the day "
        "gives you the role at 19:00 (in time for its night action); plundering at night gives it at 08:00 (in "
        "time for its day action). You can't plunder the grave of a Skeleton."
    )
    abilities = (
        Ability(
            "rob", Timing.ANYTIME, "Plunder a dead player's grave and take over their role",
            params=(P.dead("target", "Whose grave to plunder"),),
            priority=Priority.CONVERT, leaves_house=True, visits=None, uses=1,
        ),
    )

    def apparent_faction(self, state: GameState, observer: str) -> str | None:
        # before robbing a grave the Grave Robber has no faction yet: the Seer sees their role instead
        return NO_FACTION if observer == "seer" else None

    def validate(self, state: GameState, action: SubmittedAction) -> None:
        target = state.player(action.target)
        if target.life is LifeState.PERMA_DEAD or target.has_modifier("skeleton"):
            raise GameError("You can't plunder the grave of a Skeleton.")
        if target.role is None or target.role.name == "_missing":
            raise GameError("There is nothing to take from this grave.")

    def resolve_rob(self, ctx: Resolution, action: SubmittedAction) -> None:
        target = ctx.state.player(ctx.target_of(action))
        # simultaneity: the role is read now, before anything else this moment
        # changes - e.g. the Lich raising the same body tonight doesn't matter
        stolen = target.role.name
        me = self.player(ctx.state)
        ctx.inform(self.owner, f"You plundered the grave of {target.display_name}. They were the "
                               f"**{target.role.title()}** - that is now your role.")
        ctx.note("Conversions", f"{me.display_name} (Grave Robber) takes over the {stolen} of {target.display_name}")
        ctx.commit(lambda: set_role(ctx.state, me, stolen, reason=f"plundered {target.display_name}'s grave",
                                    note=f"You plundered {target.display_name}'s grave."))


class GraveRobberCommands(RoleCommands, group_name="grave_robber", source="grave_robber"):
    @app_commands.command(name="rob", description="Plunder a dead player's grave and take over their role")
    @app_commands.describe(target="Whose grave to plunder")
    async def rob(self, interaction: discord.Interaction, target: discord.Member) -> None:
        await self.use(interaction, "rob", target=target)

    @app_commands.command(name="cancel", description="Cancel your plundering before it resolves")
    async def cancel_rob(self, interaction: discord.Interaction) -> None:
        await self.cancel(interaction, "rob")
