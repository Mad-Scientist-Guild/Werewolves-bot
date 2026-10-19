import math

from Roles.role import *


@register_role
class Prophet(Role):
    name = "prophet"
    display = "Prophet"
    faction = VILLAGERS
    tags = frozenset({"villager_role"})
    description = (
        "Every night you can pray for a role. If a living player has it, you receive a list of a third of the "
        "living players, at least one of whom has that role. If nobody alive has it, you're told so."
    )
    abilities = (
        Ability(
            "pray", Timing.NIGHT, "Pray for a role",
            params=(P.role("role", "The role to pray for"),), priority=Priority.INFO,
        ),
    )

    def resolve_pray(self, ctx: Resolution, action: SubmittedAction) -> None:
        role = action.params["role"]
        title = ROLE_REGISTRY[role].title()
        alive = ctx.state.alive_players()
        holders = [p.user_id for p in alive if p.role_name == role]
        if not holders:
            ctx.inform(self.owner, f"Your prayers go unanswered: nobody alive is the **{title}**.")
            return
        size = max(1, math.ceil(len(alive) / 3))
        holder = ctx.choice(holders)
        others = sorted(p.user_id for p in alive if p.user_id not in (holder, self.owner))
        picks = [holder] + ctx.rng.sample(others, min(size - 1, len(others)))
        names = ", ".join(f"**{n}**" for n in sorted(ctx.state.name(p) for p in picks))
        ctx.inform(self.owner, f"Your prayers are answered. At least one of these is the **{title}**: {names}.")


class ProphetCommands(RoleCommands, group_name="prophet", source="prophet"):
    @app_commands.command(name="pray", description="Pray for a role tonight")
    @app_commands.describe(role="The role to pray for")
    @app_commands.autocomplete(role=role_autocomplete)
    async def pray(self, interaction: discord.Interaction, role: str) -> None:
        await self.use(interaction, "pray", role=role)

    @app_commands.command(name="cancel", description="Cancel tonight's prayer")
    async def cancel_pray(self, interaction: discord.Interaction) -> None:
        await self.cancel(interaction, "pray")
