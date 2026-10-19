from Roles.role import *


@register_role
class Priest(Role):
    name = "priest"
    display = "Priest"
    faction = VILLAGERS
    tags = frozenset({"villager_role"})
    description = (
        "Twice per game you can bless a family during the day: nobody in that family can die during the coming "
        "night - except a lover dying of a broken heart. (Being turned isn't dying, so a blessing doesn't stop it.)"
    )
    abilities = (
        Ability(
            "bless", Timing.DAY, "Bless a family: nobody in it can die tonight",
            params=(P.living("member", "Anyone in the family you want to bless", allow_self=True),),
            priority=Priority.PROTECT, uses=2,
        ),
    )

    def resolve_bless(self, ctx: Resolution, action: SubmittedAction) -> None:
        member = action.params["member"]
        house = ctx.state.house_of(member)
        family = ctx.state.house_members(house)
        label = ctx.state.groups[house].name if house in ctx.state.groups else ctx.state.name(member)
        expires = f"morning:{ctx.state.day + 1}"
        ctx.inform(self.owner, f"You blessed the family of **{ctx.state.name(member)}** for the coming night.")
        ctx.note("Protections", f"The Priest blesses {label}: {', '.join(p.display_name for p in family)}")

        def bless() -> None:
            for player in family:
                add_status(ctx.state, player, "protection", source=self.owner, expires=expires,
                           label="blessed by the Priest", turn=False)

        ctx.commit(bless)


class PriestCommands(RoleCommands, group_name="priest", source="priest"):
    @app_commands.command(name="bless", description="Bless a family for the coming night (2× per game)")
    @app_commands.describe(member="Anyone in the family you want to bless (yourself is fine)")
    async def bless(self, interaction: discord.Interaction, member: discord.Member) -> None:
        await self.use(interaction, "bless", member=member)

    @app_commands.command(name="cancel", description="Cancel today's blessing")
    async def cancel_bless(self, interaction: discord.Interaction) -> None:
        await self.cancel(interaction, "bless")
