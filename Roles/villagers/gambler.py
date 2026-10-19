from Roles.role import *


@register_role
class Gambler(Role):
    name = "gambler"
    display = "Gambler"
    faction = VILLAGERS
    tags = frozenset({"villager_role"})
    description = (
        "Once a night you can visit a player and learn their full role. But if they belong to an evil faction "
        "(Werewolves, Undead or Coven) you die tragically. Visiting the Lich kills you and turns you into a Skeleton."
    )
    abilities = (
        Ability(
            "visit", Timing.NIGHT, "Visit a player and learn their role - deadly if they're evil",
            params=(P.living("target", "Who to visit"),), priority=Priority.INFO, leaves_house=True,
        ),
    )

    def resolve_visit(self, ctx: Resolution, action: SubmittedAction) -> None:
        target = ctx.state.player(ctx.target_of(action))
        role = ctx.apparent_role(target.user_id, self.name)
        title = ROLE_REGISTRY[role].title() if role in ROLE_REGISTRY else role
        ctx.inform(self.owner, f"You visited **{target.display_name}**: they are the **{title}**.")
        faction = target.true_faction()
        if faction not in EVIL_FACTIONS:
            return
        ctx.inform(self.owner, "...and they were evil. You did not survive the visit.")
        # TODO(gambler): the GMs haven't decided whether protections (Silver Angel, Priest blessing,
        # Enchantress charm) can save the Gambler. For now protections apply, and the GMs are alerted
        # whenever one did, so they can override with /gm override kill if needed.
        kill = ctx.kill(self.owner, "gambler", killers=[target.user_id], killer_role=target.role_name,
                        attacker_faction=faction, enters_house=False, action=action)

        def check() -> None:
            if kill.prevented_by:
                ctx.note("Notes", f"Gambler {ctx.state.name(self.owner)} survived visiting an evil player "
                                  f"({kill.prevented_by}) - rule undecided, check this.")
                ctx.state.log("GAMBLER", f"{ctx.state.name(self.owner)} survived visiting evil "
                                         f"{target.display_name} because: {kill.prevented_by}. The protection rule for "
                                         "the Gambler is undecided - override if needed.", alert=True)
            elif target.role_name == "lich" and "skeleton" in CONVERSIONS:
                ctx.convert("skeleton", self.owner, by=target.user_id)

        ctx.commit(check, order=Resolution.LATE)


class GamblerCommands(RoleCommands, group_name="gambler", source="gambler"):
    @app_commands.command(name="visit", description="Visit a player tonight and learn their role (deadly if evil)")
    @app_commands.describe(target="Who to visit")
    async def visit(self, interaction: discord.Interaction, target: discord.Member) -> None:
        await self.use(interaction, "visit", target=target)

    @app_commands.command(name="cancel", description="Cancel tonight's visit")
    async def cancel_visit(self, interaction: discord.Interaction) -> None:
        await self.cancel(interaction, "visit")
