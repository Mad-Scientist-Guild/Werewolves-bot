from Roles.role import *


@register_role
class Witch(Role):
    name = "witch"
    display = "Witch"
    faction = VILLAGERS
    tags = frozenset({"villager_role"})
    description = (
        "You have two potions, each usable once. The **potion of death** (at night) kills a player by the next "
        "morning. The **elixir of life** (during the day) brings back someone who died last night - they return "
        "after the lynch. Using a potion means leaving your house. A Village Slut visiting your victim dies with "
        "them; if the Slut is your victim but isn't home, nothing happens and you keep the potion."
    )
    abilities = (
        Ability("poison", Timing.NIGHT, "Use your potion of death on a player",
                params=(P.living("target", "Who to poison"),), priority=Priority.KILL, leaves_house=True, uses=1),
        Ability("revive", Timing.DAY, "Use your elixir of life on someone who died last night",
                params=(P.dead("target", "Who to bring back"),), priority=Priority.POST, leaves_house=True, uses=1),
    )

    def validate(self, state: GameState, action: SubmittedAction) -> None:
        if action.ability != "revive":
            return
        body = state.player(action.target)
        death = body.death
        if body.life is not LifeState.DEAD or death is None or death.phase != "night" or death.day != state.day - 1:
            raise GameError("The elixir only works on someone who died last night.")

    def resolve_poison(self, ctx: Resolution, action: SubmittedAction) -> None:
        kill = ctx.kill(ctx.target_of(action), "witch", killers=[self.owner], killer_role=self.name,
                        attacker_faction=VILLAGERS, action=action)

        def keep_potion_if_not_home() -> None:
            if kill.prevented_by and kill.prevented_by.startswith("not home"):
                self.refund("poison")
                ctx.inform(self.owner, f"{ctx.state.name(kill.target)} wasn't home - your potion of death is unused.")

        ctx.commit(keep_potion_if_not_home, order=Resolution.LATE)

    def resolve_revive(self, ctx: Resolution, action: SubmittedAction) -> None:
        target = action.target

        def revive() -> None:   # LATE: after the lynch
            ctx.revive(target, reason="the Witch's elixir of life")
            ctx.inform(target, "You feel warmth returning to your body... the Witch has brought you back to life!")

        ctx.commit(revive, order=Resolution.LATE)


class WitchCommands(RoleCommands, group_name="witch", source="witch"):
    @app_commands.command(name="poison", description="Use your potion of death tonight (once per game)")
    @app_commands.describe(target="Who to poison")
    async def poison(self, interaction: discord.Interaction, target: discord.Member) -> None:
        await self.use(interaction, "poison", target=target)

    @app_commands.command(name="revive", description="Use your elixir of life on someone who died last night")
    @app_commands.describe(target="Who to bring back (they return after the lynch)")
    async def revive(self, interaction: discord.Interaction, target: discord.Member) -> None:
        await self.use(interaction, "revive", target=target)

    @app_commands.command(name="cancel", description="Cancel a potion you haven't used yet")
    @app_commands.choices(potion=[app_commands.Choice(name="potion of death", value="poison"),
                                  app_commands.Choice(name="elixir of life", value="revive")])
    async def cancel_potion(self, interaction: discord.Interaction, potion: app_commands.Choice[str]) -> None:
        await self.cancel(interaction, potion.value)
