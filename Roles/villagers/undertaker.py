from Roles.role import *

KILLER_LABELS = {
    "werewolves": "the werewolves",
    "village": "the village (lynched)",
    "gm": "unknown causes",
    None: "unknown causes",
}


@register_role
class Undertaker(Role):
    name = "undertaker"
    display = "Undertaker"
    faction = VILLAGERS
    tags = frozenset({"villager_role"})
    description = (
        "Once a day you can examine one dead player: you learn what their role was and what role their killer "
        "had. If the werewolves killed them as a pack, you only learn that it was the werewolves."
    )
    abilities = (
        Ability(
            "examine", Timing.INSTANT, "Examine a dead player: their role and their killer's role",
            params=(P.dead("target", "Whose body to examine"),), phases=(Phase.DAY.value,),
        ),
    )

    def resolve_examine(self, ctx: Resolution, action: SubmittedAction) -> None:
        body = ctx.state.player(action.target)
        role = ROLE_REGISTRY[body.role_name].title() if body.role_name in ROLE_REGISTRY else body.role_name
        record = body.deaths[-1] if body.deaths else None
        killer = record.killer_role if record else None
        if killer in KILLER_LABELS:
            by = KILLER_LABELS[killer]
        elif killer in ROLE_REGISTRY:
            by = f"the **{ROLE_REGISTRY[killer].title()}**"
        else:
            by = killer
        ctx.inform(self.owner, f"**{body.display_name}** was the **{role}**, killed by {by}.")


class UndertakerCommands(RoleCommands, group_name="undertaker", source="undertaker"):
    @app_commands.command(name="examine", description="Examine a dead player (once a day)")
    @app_commands.describe(target="Whose body to examine")
    async def examine(self, interaction: discord.Interaction, target: discord.Member) -> None:
        await self.use(interaction, "examine", target=target)
