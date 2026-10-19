from Roles.role import *


@register_role
class Seer(Role):
    name = "seer"
    display = "Seer"
    faction = VILLAGERS
    tags = frozenset({"villager_role"})
    description = (
        "Each night, choose one person and learn their faction (Werewolves, Undead, Coven, Lovers or Villagers). "
        "If you choose someone you've looked into before, you learn their exact role instead."
    )
    abilities = (
        Ability(
            "check", Timing.NIGHT, "Learn a player's faction (or their role, if you've checked them before)",
            params=(P.living("target", "Who to look into"),), priority=Priority.INFO,
        ),
    )

    checked: list[int] = field(default_factory=list)

    def resolve_check(self, ctx: Resolution, action: SubmittedAction) -> None:
        target = ctx.target_of(action)
        name = ctx.state.name(target)
        faction = ctx.apparent_faction(target, self.name)
        # a second look - or someone without a faction (the Grave Robber before robbing) - shows the role
        if target in self.checked or faction == NO_FACTION:
            role = ctx.apparent_role(target, self.name)
            title = ROLE_REGISTRY[role].title() if role in ROLE_REGISTRY else role
            ctx.inform(self.owner, f"Your vision reveals: **{name}** is the **{title}**.")
        else:
            ctx.inform(self.owner, f"Your vision reveals: **{name}** belongs to the **{faction_display(faction)}**.")
        if target not in self.checked:
            ctx.commit(lambda: self.checked.append(target))


class SeerCommands(RoleCommands, group_name="seer", source="seer"):
    @app_commands.command(name="check", description="Learn a player's faction tonight (their role if checked before)")
    @app_commands.describe(target="Who to look into")
    async def check(self, interaction: discord.Interaction, target: discord.Member) -> None:
        await self.use(interaction, "check", target=target)

    @app_commands.command(name="cancel", description="Cancel tonight's vision")
    async def cancel_check(self, interaction: discord.Interaction) -> None:
        await self.cancel(interaction, "check")
