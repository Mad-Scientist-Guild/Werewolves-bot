from Roles.role import *
from Services.runtime import runtime


@register_role
class MonsterHunter(Role):
    name = "monster_hunter"
    display = "Monster Hunter"
    faction = VILLAGERS
    tags = frozenset({"villager_role"})
    description = (
        "First you need to find the Silver Angel: once a night, point at a player to check whether they are the "
        "Silver Angel. Once you've found them you have silver, and every night you can point at a player and kill "
        "them if they belong to an evil faction. Armed with silver, a Shadow wolf stalking you dies when you go out."
    )
    abilities = (
        Ability("search", Timing.NIGHT, "Check whether a player is the Silver Angel",
                params=(P.living("target", "Who might be the Silver Angel"),), priority=Priority.INFO,
                leaves_house=True),
        Ability("hunt", Timing.NIGHT, "Kill a player if they belong to an evil faction",
                params=(P.living("target", "Who to hunt"),), priority=Priority.KILL, leaves_house=True),
    )

    has_silver: bool = False

    def available_abilities(self, state: GameState) -> list[Ability]:
        wanted = "hunt" if self.has_silver else "search"
        return [a for a in self.abilities if a.key == wanted]

    def defeats_stalkers(self, state: GameState, action: SubmittedAction) -> bool:
        return self.has_silver

    def resolve_search(self, ctx: Resolution, action: SubmittedAction) -> None:
        target = ctx.state.player(ctx.target_of(action))
        if target.role_name == "silver_angel":
            ctx.inform(self.owner, f"**{target.display_name}** is the Silver Angel! You now have silver: from now on "
                                   "you can hunt monsters with `/monster_hunter hunt`.")
            ctx.note("Info", f"The Monster Hunter found the Silver Angel ({target.display_name})")
            ctx.commit(lambda: setattr(self, "has_silver", True))
        else:
            ctx.inform(self.owner, f"**{target.display_name}** is not the Silver Angel.")

    def resolve_hunt(self, ctx: Resolution, action: SubmittedAction) -> None:
        target = ctx.target_of(action)
        if ctx.apparent_faction(target, self.name) in EVIL_FACTIONS:
            ctx.kill(target, "monster_hunter", killers=[self.owner], killer_role=self.name,
                     attacker_faction=VILLAGERS, action=action)
        else:
            ctx.note("Kills", f"The Monster Hunter hunted {ctx.state.name(target)}, who isn't evil - nothing happens")


class MonsterHunterCommands(RoleCommands, group_name="monster_hunter", source="monster_hunter"):
    @app_commands.command(name="search", description="Check whether a player is the Silver Angel")
    @app_commands.describe(target="Who might be the Silver Angel")
    async def search(self, interaction: discord.Interaction, target: discord.Member) -> None:
        await self.use(interaction, "search", target=target)

    @app_commands.command(name="hunt", description="(With silver) kill a player if they belong to an evil faction")
    @app_commands.describe(target="Who to hunt")
    async def hunt(self, interaction: discord.Interaction, target: discord.Member) -> None:
        await self.use(interaction, "hunt", target=target)

    @app_commands.command(name="cancel", description="Cancel tonight's search or hunt")
    async def cancel_action(self, interaction: discord.Interaction) -> None:
        role = runtime.games.get(interaction.guild_id).state.player(interaction.user.id).role
        await self.cancel(interaction, "hunt" if getattr(role, "has_silver", False) else "search")
