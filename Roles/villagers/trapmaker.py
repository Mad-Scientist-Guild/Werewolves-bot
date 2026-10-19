from Roles.role import *

PACK = -1   # stands for "the werewolf pack" when picking who gets trapped


@register_role
class Trapmaker(Role):
    name = "trapmaker"
    display = "Trapmaker"
    faction = VILLAGERS
    tags = frozenset({"villager_role"})
    description = (
        "Once a night you can set a trap at one person (yourself included) - the trap is on that person, not on "
        "their whole house. If anyone visits that person, one visitor (picked at random) is caught and you learn "
        "who it was; if the werewolves attack, a random wolf is caught. Their action still happens. The newspaper "
        "will mention that a trap went off, but not where."
    )
    abilities = (
        Ability(
            "trap", Timing.NIGHT, "Set a trap at a player tonight",
            params=(P.living("target", "Who to set the trap at", allow_self=True),),
            priority=Priority.INFO, leaves_house=True,
        ),
    )

    def resolve_trap(self, ctx: Resolution, action: SubmittedAction) -> None:
        target = ctx.target_of(action)
        visitors = [v for v in ctx.visitors_of(target) if v.visitor != self.owner]
        if not visitors:
            ctx.inform(self.owner, f"Nobody walked into your trap at **{ctx.state.name(target)}**.")
            return
        pack = sorted({v.visitor for v in visitors if v.pack})
        solo = sorted({v.visitor for v in visitors if not v.pack})
        options = solo + ([PACK] if pack else [])
        picked = ctx.rng.choice(options)
        caught = ctx.choice(pack) if picked == PACK else picked
        ctx.inform(self.owner, f"Your trap at **{ctx.state.name(target)}** caught **{ctx.state.name(caught)}**!")
        ctx.newspaper("A trap went off last night (don't say where or who).")


class TrapmakerCommands(RoleCommands, group_name="trapmaker", source="trapmaker"):
    @app_commands.command(name="trap", description="Set a trap at a player tonight (yourself included)")
    @app_commands.describe(target="Who to set the trap at")
    async def trap(self, interaction: discord.Interaction, target: discord.Member) -> None:
        await self.use(interaction, "trap", target=target)

    @app_commands.command(name="cancel", description="Cancel tonight's trap")
    async def cancel_trap(self, interaction: discord.Interaction) -> None:
        await self.cancel(interaction, "trap")
