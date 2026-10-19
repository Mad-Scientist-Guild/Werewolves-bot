from Roles.role import *


@register_role
class Vigilante(Role):
    name = "vigilante"
    display = "Vigilante"
    faction = VILLAGERS
    tags = frozenset({"villager_role"})
    description = (
        "Once a night you can pick another player to kill. If you kill a Villager (the Cultist counts as one), you "
        "die of guilt the same night. A Shadow wolf waiting outside your house dies, and you still go on to kill "
        "your target."
    )
    abilities = (
        Ability(
            "shoot", Timing.NIGHT, "Kill a player tonight - if they're a villager, you die of guilt",
            params=(P.living("target", "Who to kill"),), priority=Priority.KILL, leaves_house=True,
        ),
    )

    def defeats_stalkers(self, state: GameState, action: SubmittedAction) -> bool:
        return action.ability == "shoot"

    def resolve_shoot(self, ctx: Resolution, action: SubmittedAction) -> None:
        target = ctx.target_of(action)
        innocent = ctx.apparent_faction(target, self.name) == VILLAGERS   # judged before anything changes tonight
        kill = ctx.kill(target, "vigilante", killers=[self.owner], killer_role=self.name,
                        attacker_faction=VILLAGERS, action=action)
        if not innocent:
            return

        def guilt() -> None:
            if kill.processed and kill.prevented_by is None:
                ctx.kill(self.owner, "guilt", killers=[self.owner], killer_role=self.name, enters_house=False)

        ctx.commit(guilt, order=Resolution.LATE)


class VigilanteCommands(RoleCommands, group_name="vigilante", source="vigilante"):
    @app_commands.command(name="shoot", description="Kill a player tonight (die of guilt if they're a villager)")
    @app_commands.describe(target="Who to kill")
    async def shoot(self, interaction: discord.Interaction, target: discord.Member) -> None:
        await self.use(interaction, "shoot", target=target)

    @app_commands.command(name="cancel", description="Cancel tonight's kill")
    async def cancel_shoot(self, interaction: discord.Interaction) -> None:
        await self.cancel(interaction, "shoot")
