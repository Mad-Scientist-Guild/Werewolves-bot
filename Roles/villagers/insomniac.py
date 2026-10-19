from Roles.role import *


@register_role
class Insomniac(Role):
    name = "insomniac"
    display = "Insomniac"
    faction = VILLAGERS
    tags = frozenset({"villager_role"})
    description = (
        "During the day you choose what you'll lie awake listening for tonight: how many of your family members "
        "leave the house, or how many people visit your family (any number of werewolves sounds like one wolf). "
        "If the Village Slut visits you, you learn each other's roles."
    )
    abilities = (
        Ability(
            "listen", Timing.DAY, "Choose what you'll listen for tonight",
            params=(P.choice("mode", ("leaving", "visitors"),
                             "leaving: family members going out; visitors: people visiting your family"),),
            priority=Priority.INFO,
        ),
    )

    def resolve_listen(self, ctx: Resolution, action: SubmittedAction) -> None:
        mode = action.params["mode"]
        me = self.player(ctx.state)
        ctx.commit(lambda: add_status(ctx.state, me, "insomniac", source=self.owner,
                                      expires=f"morning:{ctx.state.day + 1}", mode=mode))

    def after_resolution(self, ctx: Resolution) -> None:
        if ctx.kind != "night":
            return
        status = self.player(ctx.state).status("insomniac")
        if status is None:
            return
        family = {p.user_id for p in ctx.state.housemates(self.owner)}
        if status.data.get("mode") == "leaving":
            count = len({v.visitor for v in ctx.visits if v.visitor in family and v.visitor != self.owner})
            ctx.inform(self.owner, f"You lay awake all night: **{count}** of your family members left the house.")
            return
        visits = [v for v in ctx.visits if v.target in family and not v.blocked and v.visitor != self.owner]
        wolves = any(v.pack or ctx.state.player(v.visitor).true_faction() == WEREWOLVES for v in visits)
        others = {v.visitor for v in visits
                  if not v.pack and ctx.state.player(v.visitor).true_faction() != WEREWOLVES}
        count = len(others) + (1 if wolves else 0)
        ctx.inform(self.owner, f"You lay awake all night and heard **{count}** visitor(s) at your family's house.")


class InsomniacCommands(RoleCommands, group_name="insomniac", source="insomniac"):
    @app_commands.command(name="listen", description="Choose what you'll listen for tonight")
    @app_commands.choices(mode=[app_commands.Choice(name="family members leaving the house", value="leaving"),
                                app_commands.Choice(name="people visiting my family", value="visitors")])
    async def listen(self, interaction: discord.Interaction, mode: app_commands.Choice[str]) -> None:
        await self.use(interaction, "listen", mode=mode)
