from Roles.role import *
import Roles.werewolves.turned_wolf  # noqa: F401 - registers the werewolf conversion


@register_role
class AncientWolf(Role):
    name = "ancient_wolf"
    display = "Ancient wolf"
    faction = WEREWOLVES
    groups = ("wolves",)
    can_vote_wolf_kill = True
    description = (
        "Once per game you can spare the werewolves' victim and turn them into a werewolf instead: they join the "
        "Werewolf faction and the werewolf chat, keeping their own abilities. Only you leave the house that night. "
        "If the turn fails you keep your ability."
    )
    abilities = (
        Ability(
            "turn", Timing.NIGHT, "Turn tonight's werewolf victim into a werewolf instead of killing them",
            # runs right after curses, before movement is final: the other wolves stay home
            priority=Priority.CURSE + 1, leaves_house=True, visits=None, uses=1,
        ),
    )

    def interact_turn(self, ctx: Resolution, action: SubmittedAction) -> None:
        target = ctx.flags.get("pack_target")
        if target is None:
            ctx.block(action, "the werewolves didn't agree on a victim")
            ctx.keep_use(action)
            return
        # the pack doesn't attack; the Ancient wolf goes alone
        ctx.visits[:] = [v for v in ctx.visits if not v.pack]
        kill = ctx.flags.get("pack_kill")
        if kill is not None:
            kill.prevented_by = "turned instead of eaten (Ancient wolf)"
        ctx.redirect(action, target, reason="the werewolves' victim")
        ctx.flags["pack_turned_by"] = self.owner

    def resolve_turn(self, ctx: Resolution, action: SubmittedAction) -> None:
        target = ctx.target_of(action)
        reason = ctx.turn_prevented(target, attacker_faction=WEREWOLVES, killers=[self.owner])
        if reason:
            ctx.note("Conversions", f"Ancient wolf's turn of {ctx.state.name(target)} failed: {reason}")
            ctx.inform(self.owner, f"Your attempt to turn {ctx.state.name(target)} failed. You keep your ability.")
            ctx.keep_use(action)
            return
        ctx.claim("turn", target, self.owner)

        def commit() -> None:
            if ctx.claim_winner("turn", target) != self.owner:
                ctx.inform(self.owner, f"Your attempt to turn {ctx.state.name(target)} failed. You keep your ability.")
                self.refund("turn")
                return
            ctx.convert("werewolf", target, by=self.owner)
            ctx.note("Conversions", f"{ctx.state.name(target)} is turned into a werewolf by the Ancient wolf")
            ctx.inform(self.owner, f"You turned {ctx.state.name(target)} into a werewolf.")

        ctx.commit(commit)


class AncientWolfCommands(RoleCommands, group_name="ancient_wolf", source="ancient_wolf"):
    @app_commands.command(name="turn", description="Tonight, turn the pack's victim into a werewolf instead")
    async def turn(self, interaction: discord.Interaction) -> None:
        await self.use(interaction, "turn")

    @app_commands.command(name="cancel", description="Cancel tonight's turn")
    async def cancel_turn(self, interaction: discord.Interaction) -> None:
        await self.cancel(interaction, "turn")
