from Roles.role import *


@register_role
class FeralWolf(Role):
    name = "feral_wolf"
    display = "Feral wolf"
    faction = WEREWOLVES
    groups = ("wolves",)
    can_vote_wolf_kill = True
    description = (
        "Three times per game you can, on top of the pack's kill, go out alone and eat another player - of any "
        "faction, werewolves included. You leave your house to do this."
    )
    abilities = (
        Ability(
            "eat", Timing.NIGHT, "Eat an extra player tonight, on your own",
            params=(P.living("target", "Who to eat"),),
            priority=Priority.KILL, leaves_house=True, uses=3,
        ),
    )

    def resolve_eat(self, ctx: Resolution, action: SubmittedAction) -> None:
        ctx.kill(ctx.target_of(action), "feral_wolf", killers=[self.owner], killer_role=self.name,
                 attacker_faction=WEREWOLVES, action=action)


class FeralWolfCommands(RoleCommands, group_name="feral_wolf", source="feral_wolf"):
    @app_commands.command(name="eat", description="Eat an extra player tonight, on your own (3× per game)")
    @app_commands.describe(target="Who to eat")
    async def eat(self, interaction: discord.Interaction, target: discord.Member) -> None:
        await self.use(interaction, "eat", target=target)

    @app_commands.command(name="cancel", description="Cancel tonight's extra kill")
    async def cancel_eat(self, interaction: discord.Interaction) -> None:
        await self.cancel(interaction, "eat")
