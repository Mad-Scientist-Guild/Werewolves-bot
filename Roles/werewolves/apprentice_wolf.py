import copy

from Roles.role import *


@register_role
class ApprenticeWolf(Role):
    name = "apprentice_wolf"
    display = "Apprentice wolf"
    faction = WEREWOLVES
    groups = ("wolves",)
    can_vote_wolf_kill = True
    description = (
        "The night after a fellow wolf dies, you can take up their role - only that night, or the chance is gone. "
        "You then become that wolf, with whatever charges they had left, and lose your apprentice ability. "
        "If that wolf is ever revived, they come back as a wolf without abilities."
    )
    abilities = (
        Ability(
            "take_over", Timing.NIGHT, "Take over the role of a wolf who just died",
            params=(P.dead("target", "The fallen wolf whose role you take over"),),
            priority=Priority.CONVERT, leaves_house=True, visits=None,
        ),
    )

    offers: dict[int, int] = field(default_factory=dict)   # fallen wolf -> the one night it can be taken over

    @staticmethod
    def _is_wolf_role(player: Player) -> bool:
        role = player.role
        return role is not None and role.faction == WEREWOLVES and role.can_vote_wolf_kill

    def on_other_death(self, ctx: Resolution, dead: Player) -> None:
        if not self._is_wolf_role(dead) or not self.player(ctx.state).alive:
            return
        # "the night after": tonight if it's still day/evening, otherwise the next night
        night = ctx.state.day + 1 if ctx.state.phase is Phase.SLEEP else ctx.state.day
        self.offers[dead.user_id] = night
        ctx.inform(self.owner, f"Your fellow wolf **{dead.display_name}** has fallen. During night {night} - and only "
                               "then - you can take over their role with `/apprentice_wolf take_over`.")

    def available_abilities(self, state: GameState) -> list[Ability]:
        return list(self.abilities) if state.day in self.offers.values() else []

    def validate(self, state: GameState, action: SubmittedAction) -> None:
        if self.offers.get(action.target) != state.day:
            raise GameError("You can only take over the role of a wolf who died since the last night.")

    def resolve_take_over(self, ctx: Resolution, action: SubmittedAction) -> None:
        mentor = ctx.state.player(ctx.target_of(action))
        role = copy.deepcopy(mentor.role)        # read now: simultaneous changes don't matter
        me = self.player(ctx.state)
        ctx.note("Conversions", f"{me.display_name} (Apprentice wolf) takes over the {role.name} of {mentor.display_name}")
        ctx.inform(self.owner, f"You took up the mantle of {mentor.display_name}: you are now the **{role.title()}**.")

        def commit() -> None:
            adopt_role(ctx.state, me, role, reason=f"Apprentice took over {mentor.display_name}",
                       note=f"You took over {mentor.display_name}'s role. Its remaining charges carry over.")
            add_status(ctx.state, mentor, "becomes_on_revive", source=self.owner,
                       role="werewolf", reason="their role was taken over by the Apprentice wolf")

        ctx.commit(commit)


class ApprenticeWolfCommands(RoleCommands, group_name="apprentice_wolf", source="apprentice_wolf"):
    @app_commands.command(name="take_over", description="Take over the role of a wolf who just died")
    @app_commands.describe(target="The fallen wolf")
    async def take_over(self, interaction: discord.Interaction, target: discord.Member) -> None:
        await self.use(interaction, "take_over", target=target)

    @app_commands.command(name="cancel", description="Cancel tonight's take-over")
    async def cancel_take_over(self, interaction: discord.Interaction) -> None:
        await self.cancel(interaction, "take_over")
