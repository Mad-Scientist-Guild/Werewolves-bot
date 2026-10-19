from Roles.role import *


@register_role
class Wanderer(Role):
    name = "wanderer"
    display = "Wanderer"
    faction = VILLAGERS
    tags = frozenset({"villager_role"})
    description = (
        "At night you wander through town and spot someone who left their house, picked at random - they don't "
        "know you saw them. After the first night you can also choose to look for the same person again: you'll "
        "learn whether they went out again."
    )
    abilities = (
        Ability(
            "wander", Timing.NIGHT, "Wander the town tonight",
            params=(P.choice("mode", ("random", "same"),
                             "random: spot someone at random; same: look for the person you saw last time",
                             required=False),),
            priority=Priority.INFO, leaves_house=True, visits=None,
        ),
    )

    last_seen: int | None = None

    def validate(self, state: GameState, action: SubmittedAction) -> None:
        if action.params.get("mode") == "same" and self.last_seen is None:
            raise GameError("You haven't spotted anyone yet - wander at random first.")

    def resolve_wander(self, ctx: Resolution, action: SubmittedAction) -> None:
        if action.params.get("mode") == "same":
            seen = self.last_seen
            if ctx.left_house(seen):
                ctx.inform(self.owner, f"You found **{ctx.state.name(seen)}** out of their house again.")
            else:
                ctx.inform(self.owner, f"You looked for **{ctx.state.name(seen)}**, but they stayed at home.")
            return
        out = sorted({v.visitor for v in ctx.visits if v.visitor != self.owner})
        if not out:
            ctx.inform(self.owner, "The streets were empty - you didn't see anyone.")
            return
        seen = ctx.choice(out)
        ctx.inform(self.owner, f"While wandering, you spotted **{ctx.state.name(seen)}** outside their house.")
        ctx.commit(lambda: setattr(self, "last_seen", seen))


class WandererCommands(RoleCommands, group_name="wanderer", source="wanderer"):
    @app_commands.command(name="wander", description="Wander the town tonight")
    @app_commands.describe(mode="random (default) or same: look for the person you saw last time")
    @app_commands.choices(mode=[app_commands.Choice(name="spot someone at random", value="random"),
                                app_commands.Choice(name="look for the same person again", value="same")])
    async def wander(self, interaction: discord.Interaction, mode: app_commands.Choice[str] | None = None) -> None:
        await self.use(interaction, "wander", mode=mode)

    @app_commands.command(name="cancel", description="Stay home tonight after all")
    async def cancel_wander(self, interaction: discord.Interaction) -> None:
        await self.cancel(interaction, "wander")
