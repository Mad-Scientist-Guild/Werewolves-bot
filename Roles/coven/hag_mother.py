from Core.resolution import register_conversion
from Roles.coven._coven import CovenCommands, CovenRole, connect, full_coven
from Roles.role import *

CHANGELING_NIGHTS = 3


@register_role
class HagMother(CovenRole):
    name = "hag_mother"
    display = "Hag Mother"
    description = (
        "Once per game you can secretly pick someone in the village to be your Changeling - they don't know it. "
        "After 3 nights they grow up into a hag hybrid: they join the Coven (and your Coven group), keeping their "
        "own role and chats. If you die before that, they never grow up.\n"
        "With your motherly instinct you can search for three fellow Coven members each night instead of one. "
        "Once the whole Coven has found each other, you can check whether a role on the kill list is still alive."
    )
    abilities = (
        Ability(
            "find", Timing.NIGHT, "Search for up to three fellow Coven members",
            params=(P.living("target", "Who you think is in the Coven"),
                    P.living("target2", "Another guess", required=False),
                    P.living("target3", "Another guess", required=False)),
            priority=Priority.INFO,
        ),
        Ability(
            "changeling", Timing.NIGHT, "Secretly make someone your Changeling (once per game)",
            params=(P.living("target", "Who becomes your Changeling"),), priority=Priority.CONVERT, uses=1,
        ),
        Ability(
            "check", Timing.NIGHT, "Check whether a role on the kill list is still alive",
            params=(P.role("role", "A role on the kill list"),), priority=Priority.INFO,
        ),
    )

    def available_abilities(self, state: GameState) -> list[Ability]:
        out = super().available_abilities(state)
        return out if full_coven(state) else [a for a in out if a.key != "check"]

    def validate(self, state: GameState, action: SubmittedAction) -> None:
        super().validate(state, action)
        if action.ability == "check" and action.params["role"] not in state.data.get("coven_kill_list", []):
            raise GameError("That role isn't on the kill list.")
        if action.ability == "changeling" and state.player(action.target).true_faction() == COVEN:
            raise GameError("They're already part of the Coven.")

    def resolve_changeling(self, ctx: Resolution, action: SubmittedAction) -> None:
        target = ctx.state.player(ctx.target_of(action))
        ctx.inform(self.owner, f"**{target.display_name}** is now your Changeling. They'll grow up in "
                               f"{ctx.state.role_setting(self.name, 'changeling_nights', CHANGELING_NIGHTS)} nights.")
        ctx.note("Conversions", f"The Hag Mother makes {target.display_name} her Changeling (they don't know)")
        ctx.commit(lambda: add_modifier(ctx.state, target, "changeling", reason="the Hag Mother's choice",
                                        turned_by=self.owner, since_night=ctx.state.day))

    def resolve_check(self, ctx: Resolution, action: SubmittedAction) -> None:
        role = action.params["role"]
        alive = any(p.alive and p.original_role == role for p in ctx.state.players.values())
        title = ROLE_REGISTRY[role].title() if role in ROLE_REGISTRY else role
        ctx.inform(self.owner, f"The **{title}** is {'still alive' if alive else 'no longer among the living'}.")


@register_modifier
class Changeling(Modifier):
    """Acquired: chosen by the Hag Mother. Hidden until it grows up."""
    name = "changeling"
    display = "Changeling"
    description = (
        "You've grown up into a hag hybrid! You keep your role, its abilities and your chats, but you now win with "
        "the Coven. You've found the Hag Mother: you share her Coven group."
    )

    turned_by: int | None = None
    since_night: int = 0
    grown: bool = False
    withered: bool = False   # the Hag Mother died before it grew up

    def faction_override(self, player: Player) -> str | None:
        return COVEN if self.grown else None

    def after_resolution(self, ctx: Resolution) -> None:
        if ctx.kind != "night" or self.grown or self.withered:
            return
        hag = ctx.state.find_player(self.turned_by)
        if hag is None or not hag.alive:
            self.withered = True
            ctx.note("Conversions", f"The Changeling {ctx.state.name(self.owner)} won't grow up: the Hag Mother is gone")
            return
        nights = ctx.state.role_setting("hag_mother", "changeling_nights", CHANGELING_NIGHTS)
        if ctx.state.day - self.since_night >= nights:
            ctx.convert("changeling", self.owner, by=hag.user_id)


def grow_up(ctx: Resolution, target: int, by: int) -> None:
    """The "changeling" conversion: the Changeling becomes a hag hybrid."""
    player = ctx.state.player(target)
    changeling = player.modifier("changeling")
    changeling.grown = True
    ctx.inform(target, "🌑 You feel a strange change... you've grown up into a **hag hybrid**. You now belong to the "
                       "**Coven**, keeping your own role and abilities, and you know the Hag Mother: "
                       f"**{ctx.state.name(by)}**.")
    ctx.note("Conversions", f"{player.display_name} grows up into a hag hybrid (Coven)")
    connect(ctx, target, by)   # counts as finding the Hag Mother: joins her Coven group


register_conversion("changeling", grow_up)


class HagMotherCommands(CovenCommands, group_name="hag_mother", source="hag_mother"):
    @app_commands.command(name="find", description="Search for up to three fellow Coven members tonight")
    @app_commands.describe(target="A guess", target2="Another guess", target3="Another guess")
    async def find(self, interaction: discord.Interaction, target: discord.Member,
                   target2: discord.Member | None = None, target3: discord.Member | None = None) -> None:
        await self.use(interaction, "find", target=target, target2=target2, target3=target3)

    @app_commands.command(name="changeling", description="Secretly make someone your Changeling (once per game)")
    @app_commands.describe(target="Who becomes your Changeling")
    async def changeling(self, interaction: discord.Interaction, target: discord.Member) -> None:
        await self.use(interaction, "changeling", target=target)

    @app_commands.command(name="check", description="Is a role on the kill list still alive? (whole Coven found)")
    @app_commands.describe(role="A role on the kill list")
    @app_commands.autocomplete(role=role_autocomplete)
    async def check(self, interaction: discord.Interaction, role: str) -> None:
        await self.use(interaction, "check", role=role)
