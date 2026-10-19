from Core.effects import Announcement
from Roles.lovers.lover import turned
from Roles.role import *

BOND = "protected by the bond of love"


@register_role
class Cupid(Role):
    name = "cupid"
    display = "Cupid"
    faction = LOVERS
    description = (
        "On the first night you link two people (you may pick yourself): they fall in love, share a chat, and die "
        "of a broken heart if the other dies. You and the lovers win if the lovers (and maybe you) are alive at "
        "the end. While both lovers live, you can't die from a lynch - the village learns you're Cupid instead. "
        "Once a lover dies, you join the Villagers."
    )
    abilities = (
        Ability(
            "link", Timing.NIGHT, "Make two players fall in love (first night only)",
            params=(P.living("first", "The first lover", allow_self=True),
                    P.living("second", "The second lover", allow_self=True)),
            priority=Priority.CONVERT, visits=None, uses=1,
        ),
    )

    lovers: list[int] = field(default_factory=list)

    def available_abilities(self, state: GameState) -> list[Ability]:
        return list(self.abilities) if state.day == 1 and not self.lovers else []

    def validate(self, state: GameState, action: SubmittedAction) -> None:
        if action.params["first"] == action.params["second"]:
            raise GameError("Pick two different people.")
        for target in action.targets:
            if state.player(target).has_modifier("lover"):
                raise GameError(f"{state.name(target)} is already in love.")

    def resolve_link(self, ctx: Resolution, action: SubmittedAction) -> None:
        first, second = action.params["first"], action.params["second"]
        state = ctx.state
        ctx.note("Conversions", f"Cupid links {state.name(first)} and {state.name(second)}")

        def link() -> None:
            self.lovers = [first, second]
            group = state.ensure_group(f"lovers:{self.owner}", GroupKind.LOVERS, "lovers")
            for me, partner in ((first, second), (second, first)):
                add_modifier(state, state.player(me), "lover", partner=partner, cupid=self.owner,
                             reason="struck by Cupid's arrow")
                group.add(me)
                ctx.inform(me, f"💘 Cupid's arrow struck you: you are in love with **{state.name(partner)}**! You "
                               "share a chat now. If one of you dies, the other dies of a broken heart.")
            for me, partner in ((first, second), (second, first)):
                if turned(state.player(partner)):   # turned the same night: the bond doesn't make them win together
                    state.player(me).modifier("lover").bond_broken = True
            ctx.inform(self.owner, f"You linked **{state.name(first)}** and **{state.name(second)}**.")

        ctx.commit(link)

    def protects_against(self, ctx: Resolution, kill: Kill) -> str | None:
        if kill.cause == "lynch" and self.lovers and all(ctx.state.player(lover).alive for lover in self.lovers):
            return BOND
        return None

    def on_kill_prevented(self, ctx: Resolution, kill: Kill) -> None:
        if kill.cause == "lynch" and kill.prevented_by == BOND:
            ctx.state.emit(Announcement(title="CUPID", text=f"**{ctx.state.name(self.owner)}** is **Cupid**! The bond of "
                                                            "love protects them from the rope."))

    def on_other_death(self, ctx: Resolution, dead: Player) -> None:
        me = self.player(ctx.state)
        if dead.user_id in self.lovers and me.faction != VILLAGERS:
            me.faction = VILLAGERS
            ctx.inform(self.owner, "One of your lovers has died. You now belong to the **Villagers**.")
            ctx.note("Conversions", f"Cupid {me.display_name} joins the Villagers")


class CupidCommands(RoleCommands, group_name="cupid", source="cupid"):
    @app_commands.command(name="link", description="Make two players fall in love (first night only)")
    @app_commands.describe(first="The first lover (may be you)", second="The second lover")
    async def link(self, interaction: discord.Interaction, first: discord.Member, second: discord.Member) -> None:
        await self.use(interaction, "link", first=first, second=second)
