from Core import voting
from Roles.role import *


def open_lynch(state: GameState) -> str:
    for kind in (voting.LYNCH2, voting.LYNCH):
        ballot = state.ballots.get(kind)
        if ballot is not None and ballot.is_open:
            return kind
    raise GameError("Voting isn't open right now.")


@register_role
class CunningWolf(Role):
    name = "cunning_wolf"
    display = "Cunning wolf"
    faction = WEREWOLVES
    groups = ("wolves",)
    can_vote_wolf_kill = True
    description = (
        "When you vote in the lynch you can name a second player: when the votes are published, that name is "
        "listed as your vote instead of the player you really voted for. Your real vote is what counts. "
        "(A normal `/lynch vote` works too.)"
    )
    abilities = (
        Ability(
            "vote", Timing.INSTANT, "Vote in the lynch, with a different name shown when the votes are published",
            params=(P.living("target", "Who you really vote for", allow_self=True),
                    P.living("shown_as", "The name that will be published as your vote", allow_self=True)),
            once_per_cycle=False, phases=(Phase.DAY.value, Phase.NIGHT.value),
        ),
    )

    def validate(self, state: GameState, action: SubmittedAction) -> None:
        open_lynch(state)

    def resolve_vote(self, ctx: Resolution, action: SubmittedAction) -> None:
        kind = open_lynch(ctx.state)
        target, shown = action.params["target"], action.params["shown_as"]
        ctx.note("Notes", f"Cunning wolf votes for {ctx.state.name(target)}, published as {ctx.state.name(shown)}")
        ctx.commit(lambda: voting.cast_vote(ctx.state, kind, self.owner, target, at=action.submitted_at, shown_as=shown))


class CunningWolfCommands(RoleCommands, group_name="cunning_wolf", source="cunning_wolf"):
    @app_commands.command(name="vote", description="Lynch vote with a different name shown when votes are published")
    @app_commands.describe(target="Who you really vote for", shown_as="The name published as your vote")
    async def vote(self, interaction: discord.Interaction, target: discord.Member, shown_as: discord.Member) -> None:
        await self.use(interaction, "vote", target=target, shown_as=shown_as)
