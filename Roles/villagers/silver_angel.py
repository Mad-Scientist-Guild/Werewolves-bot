"""Silver Angel - the reference example of a role file.

A role file has two parts:
  1. the Role class: rules, state and resolution logic (pure, no Discord)
  2. the commands class: the slash commands players use (thin wrappers)

Nothing else needs to change anywhere to add a role - drop the file in a
faction folder under Roles/ and it's picked up automatically.
"""
from Roles.role import *


@register_role
class SilverAngel(Role):
    # identity -------------------------------------------------------------
    name = "silver_angel"                 # unique key; used in commands, the role pool and the database
    display = "Silver Angel"
    faction = VILLAGERS
    tags = frozenset({"villager_role"})
    description = (
        "Every night you may protect one person (yourself included). They can't die that night from the "
        "Werewolves, the Coven or the Undead, and your protection also stops them from being turned. "
        "You can't protect the same person two nights in a row. The Monster Hunter is looking for you."
    )

    # what the role can do -------------------------------------------------
    abilities = (
        Ability(
            "protect", Timing.NIGHT, "Protect a player tonight",
            params=(P.living("target", "Who to protect", allow_self=True),),
            priority=Priority.PROTECT,
            leaves_house=True,            # the Silver Angel leaves the house when protecting
        ),
    )

    # state - saved to the database automatically -------------------------
    last_protected: int | None = None

    # validation at submit time (generic checks already ran) --------------
    def validate(self, state: GameState, action: SubmittedAction) -> None:
        if action.target is not None and action.target == self.last_protected:
            raise GameError("You can't protect the same person two nights in a row.")

    # resolution -----------------------------------------------------------
    # interact_<ability> runs in the interaction pass (only if the action wasn't
    # blocked by a lock, curse, ...). Protections must be registered there so
    # they apply to kills evaluated later.
    def interact_protect(self, ctx: Resolution, action: SubmittedAction) -> None:
        target = ctx.target_of(action)
        ctx.protect(
            target, "protected by the Silver Angel",
            lambda kill: kill.attacker_faction in EVIL_FACTIONS,   # also matches turning (cause "turn")
        )
        ctx.flags[f"silver_angel_protected:{self.owner}"] = target

    def after_resolution(self, ctx: Resolution) -> None:
        # runs in the commit pass, so changing state here is allowed
        if ctx.kind == "night":
            self.last_protected = ctx.flags.get(f"silver_angel_protected:{self.owner}")


class SilverAngelCommands(RoleCommands, group_name="silver_angel", source="silver_angel"):
    @app_commands.command(name="protect", description="Protect a player tonight (yourself included)")
    @app_commands.describe(target="Who to protect")
    async def protect(self, interaction: discord.Interaction, target: discord.Member) -> None:
        await self.use(interaction, "protect", target=target)

    @app_commands.command(name="cancel", description="Cancel tonight's protection")
    async def cancel_protect(self, interaction: discord.Interaction) -> None:
        await self.cancel(interaction, "protect")
