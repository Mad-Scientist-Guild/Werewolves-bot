from Roles.role import *


@register_role
class Fox(Role):
    name = "fox"
    display = "Fox"
    faction = VILLAGERS
    tags = frozenset({"villager_role"})
    description = (
        "Once a night you can point at three people. If at least one of them is not a Villager, you're told so. "
        "If all three are Villagers, you're told that too - and you lose your ability for the rest of the game."
    )
    abilities = (
        Ability(
            "sniff", Timing.NIGHT, "Point at three players: learn whether any of them is not a villager",
            params=(P.living("first", "First player"), P.living("second", "Second player"),
                    P.living("third", "Third player")),
            priority=Priority.INFO, visits=None,
        ),
    )

    active: bool = True

    def available_abilities(self, state: GameState) -> list[Ability]:
        return list(self.abilities) if self.active else []

    def validate(self, state: GameState, action: SubmittedAction) -> None:
        if len(set(action.targets)) != 3:
            raise GameError("Point at three different players.")

    def resolve_sniff(self, ctx: Resolution, action: SubmittedAction) -> None:
        targets = [ctx.target_of(action, "first"), action.params["second"], action.params["third"]]
        names = ", ".join(f"**{ctx.state.name(t)}**" for t in targets)
        if any(ctx.apparent_faction(t, self.name) != VILLAGERS for t in targets):
            ctx.inform(self.owner, f"Among {names}, at least one is **not** a Villager.")
            return
        ctx.inform(self.owner, f"{names} are all Villagers. Your nose has lost its edge: you can't use your "
                               "ability any more.")
        ctx.commit(lambda: setattr(self, "active", False))


class FoxCommands(RoleCommands, group_name="fox", source="fox"):
    @app_commands.command(name="sniff", description="Point at three players: is any of them not a villager?")
    async def sniff(self, interaction: discord.Interaction, first: discord.Member, second: discord.Member,
                    third: discord.Member) -> None:
        await self.use(interaction, "sniff", first=first, second=second, third=third)

    @app_commands.command(name="cancel", description="Cancel tonight's sniffing")
    async def cancel_sniff(self, interaction: discord.Interaction) -> None:
        await self.cancel(interaction, "sniff")
