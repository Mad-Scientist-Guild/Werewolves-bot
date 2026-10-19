import Roles.undead.skeleton  # noqa: F401 - registers the skeleton conversion
from Roles.role import *

ONLY_LYNCH = "the Lich can only die by lynching"


@register_role
class Lich(Role):
    name = "lich"
    display = "Lich"
    faction = UNDEAD
    groups = ("undead",)
    description = (
        "You must raise an army to take over the town. Once a night you can pick two different dead players and "
        "guess their roles: everyone you guess right rises as your Skeleton and joins your private chat. You can "
        "only die by lynching - but when you die, all your skeletons die with you."
    )
    abilities = (
        Ability(
            "raise", Timing.NIGHT, "Guess the roles of up to two dead players - correct guesses rise as Skeletons",
            params=(P.dead("first", "A dead player"), P.role("first_role", "Your guess for their role"),
                    P.dead("second", "Another dead player", required=False),
                    P.role("second_role", "Your guess for their role", required=False)),
            priority=Priority.CONVERT, leaves_house=True, visits=None,
        ),
    )

    def validate(self, state: GameState, action: SubmittedAction) -> None:
        params = action.params
        if ("second" in params) != ("second_role" in params):
            raise GameError("Give a role guess for the second player too (or leave both out).")
        if params.get("second") == params["first"]:
            raise GameError("Pick two different dead players.")
        for target in action.targets:
            if state.player(target).life is LifeState.PERMA_DEAD:
                raise GameError(f"{state.name(target)} was a Skeleton once - they can't rise again.")

    def resolve_raise(self, ctx: Resolution, action: SubmittedAction) -> None:
        pairs = [(action.params["first"], action.params["first_role"])]
        if "second" in action.params:
            pairs.append((action.params["second"], action.params["second_role"]))
        for target, guess in pairs:
            body = ctx.state.player(target)
            if body.role_name == guess:
                ctx.inform(self.owner, f"Your guess was right: **{body.display_name}** rises from the grave.")
                ctx.commit(lambda t=target: ctx.convert("skeleton", t, by=self.owner))
            else:
                ctx.inform(self.owner, f"The grave of **{body.display_name}** stays quiet - your guess was wrong.")

    def protects_against(self, ctx: Resolution, kill: Kill) -> str | None:
        return None if kill.cause == "lynch" else ONLY_LYNCH

    def on_death(self, ctx: Resolution, record: DeathRecord) -> None:
        for player in ctx.state.players.values():
            skeleton = player.modifier("skeleton")
            if skeleton is not None and skeleton.lich == self.owner and player.life is LifeState.SKELETON:
                ctx.kill(player.user_id, "the Lich died", killers=[self.owner], killer_role=self.name,
                         unstoppable=True, enters_house=False)


class LichCommands(RoleCommands, group_name="lich", source="lich"):
    @app_commands.command(name="raise", description="Guess the roles of up to two dead players to raise them")
    @app_commands.describe(first="A dead player", first_role="Your guess for their role",
                           second="Another dead player", second_role="Your guess for their role")
    @app_commands.autocomplete(first_role=role_autocomplete, second_role=role_autocomplete)
    async def raise_dead(self, interaction: discord.Interaction, first: discord.Member, first_role: str,
                         second: discord.Member | None = None, second_role: str | None = None) -> None:
        await self.use(interaction, "raise", first=first, first_role=first_role, second=second,
                       second_role=second_role)

    @app_commands.command(name="cancel", description="Cancel tonight's raising")
    async def cancel_raise(self, interaction: discord.Interaction) -> None:
        await self.cancel(interaction, "raise")
