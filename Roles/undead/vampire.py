from Core import flow
from Core.resolution import register_conversion
from Roles.role import *


@register_modifier
class VampireSpawn(Modifier):
    """Acquired: bitten and turned by the Vampire Lord. Keeps their role,
    abilities and chats, but wins with the Undead."""
    name = "vampire_spawn"
    display = "Vampire Spawn"
    description = (
        "The Vampire Lord turned you into a Vampire Spawn. You keep your role, its abilities and your chats, but "
        "you now win with the Undead and share their chat. Every kill the Vampire Lord makes counts for you too: "
        "if the Lord dies after you've shared in a kill, you become the new Vampire Lord."
    )
    true_faction = UNDEAD
    groups = ("undead",)

    turned_by: int | None = None
    participated: bool = False


def make_spawn(ctx: Resolution, target: int, by: int) -> None:
    """The "vampire" conversion (commit pass)."""
    player = ctx.state.player(target)
    add_modifier(ctx.state, player, "vampire_spawn", reason=f"turned by {ctx.state.name(by)}", turned_by=by)
    ctx.inform(target, "🧛 You were bitten... and woke up hungry. You are now a **Vampire Spawn**: you keep your "
                       "role but win with the Undead, and you've joined their chat.")


register_conversion("vampire", make_spawn)


def living_spawns(state: GameState) -> list[Player]:
    return [p for p in state.alive_players() if p.has_modifier("vampire_spawn")]


def promote(state: GameState, spawn: Player, *, reason: str) -> None:
    flow.remove_modifier(state, spawn, "vampire_spawn", reason=reason)
    flow.set_role(state, spawn, "vampire_lord", reason=reason,
                  note="The Vampire Lord is dead - you have taken their place (and lost your previous ability).")


def _decide_new_lord(state: GameState, decision, result) -> None:
    promote(state, state.player(decision.choice), reason="chosen by the spawns as the new Vampire Lord")


flow.DECISION_HANDLERS["new_vampire_lord"] = _decide_new_lord


@register_role
class VampireLord(Role):
    name = "vampire_lord"
    display = "Vampire Lord"
    faction = UNDEAD
    groups = ("undead",)
    description = (
        "Every night you can bite a player to kill them. While you have no Vampire Spawn you may instead turn your "
        "victim into one: they join the Undead (and your chat) the next morning, keeping their own abilities. "
        "Turning only works if you're still alive. If you and the Ancient wolf turn the same person, one fails."
    )
    abilities = (
        Ability(
            "bite", Timing.NIGHT, "Bite a player tonight - kill them, or turn them into your Spawn",
            params=(P.living("target", "Who to bite"),
                    P.choice("mode", ("kill", "turn"), "kill (default) or turn into a Vampire Spawn", required=False)),
            priority=Priority.KILL, leaves_house=True,
        ),
    )

    def validate(self, state: GameState, action: SubmittedAction) -> None:
        if action.params.get("mode") == "turn" and living_spawns(state):
            raise GameError("You already have a Vampire Spawn - you can only kill.")

    def resolve_bite(self, ctx: Resolution, action: SubmittedAction) -> None:
        target = ctx.target_of(action)
        if action.params.get("mode") == "turn":
            self._turn(ctx, action, target)
            return
        ctx.kill(target, "vampire", killers=[self.owner], killer_role=self.name, attacker_faction=UNDEAD,
                 action=action)

    def on_other_killed(self, ctx: Resolution, kill: Kill) -> None:
        # every kill of the Lord counts for the spawns - no matter the order deaths are processed in
        if kill.cause == "vampire" and self.owner in kill.killers:
            for spawn in living_spawns(ctx.state):
                spawn.modifier("vampire_spawn").participated = True

    def _turn(self, ctx: Resolution, action: SubmittedAction, target: int) -> None:
        reason = ctx.turn_prevented(target, attacker_faction=UNDEAD, killers=[self.owner])
        if reason:
            ctx.note("Conversions", f"The Vampire Lord's turn of {ctx.state.name(target)} failed: {reason}")
            ctx.inform(self.owner, f"Your attempt to turn {ctx.state.name(target)} failed.")
            return
        ctx.claim("turn", target, self.owner)

        def commit() -> None:   # LATE: the Lord must still be alive after tonight's deaths
            if ctx.claim_winner("turn", target) != self.owner:
                ctx.inform(self.owner, f"Your attempt to turn {ctx.state.name(target)} failed.")
                return
            if not self.player(ctx.state).alive:
                ctx.note("Conversions", f"{ctx.state.name(target)} isn't turned: the Vampire Lord died")
                return
            ctx.convert("vampire", target, by=self.owner)
            ctx.note("Conversions", f"{ctx.state.name(target)} is turned into a Vampire Spawn")
            ctx.inform(self.owner, f"You turned **{ctx.state.name(target)}** into your Vampire Spawn.")

        ctx.commit(commit, order=Resolution.LATE)

    def on_death(self, ctx: Resolution, record: DeathRecord) -> None:
        ctx.flags[f"vampire_lord_died:{self.owner}"] = True

    def after_resolution(self, ctx: Resolution) -> None:
        # decided at the very end, so a bite in the same night as the Lord's death still counts
        if not ctx.flags.pop(f"vampire_lord_died:{self.owner}", False):
            return
        ready = [s for s in living_spawns(ctx.state) if s.modifier("vampire_spawn").participated]
        if len(ready) == 1:
            promote(ctx.state, ready[0], reason="the Vampire Lord died")
            ctx.note("Conversions", f"{ready[0].display_name} becomes the new Vampire Lord")
        elif len(ready) > 1:
            flow.create_decision(
                ctx.state, "new_vampire_lord", None, [s.user_id for s in ready],
                "The Vampire Lord died and several spawns shared in a kill. They decide together who becomes the "
                "new Vampire Lord - ask them in the undead chat and pick their choice:")


class VampireLordCommands(RoleCommands, group_name="vampire_lord", source="vampire_lord"):
    @app_commands.command(name="bite", description="Bite a player tonight: kill them, or turn them into your Spawn")
    @app_commands.describe(target="Who to bite", mode="kill (default) or turn (only while you have no Spawn)")
    @app_commands.choices(mode=[app_commands.Choice(name="kill", value="kill"),
                                app_commands.Choice(name="turn into a Vampire Spawn", value="turn")])
    async def bite(self, interaction: discord.Interaction, target: discord.Member,
                   mode: app_commands.Choice[str] | None = None) -> None:
        await self.use(interaction, "bite", target=target, mode=mode)

    @app_commands.command(name="cancel", description="Cancel tonight's bite")
    async def cancel_bite(self, interaction: discord.Interaction) -> None:
        await self.cancel(interaction, "bite")
