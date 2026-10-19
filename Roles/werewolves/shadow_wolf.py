from Roles.role import *


@register_role
class ShadowWolf(Role):
    name = "shadow_wolf"
    display = "Shadow wolf"
    faction = WEREWOLVES
    groups = ("wolves",)
    can_vote_wolf_kill = True
    description = (
        "Once a night you can stalk a player. If they leave their house, you are waiting for them: they're forced "
        "back and their night action fails (limited uses aren't lost). They'll know the Shadow wolf visited. "
        "You can never stalk the same player twice. Beware: a Vigilante going out to kill, or a Monster Hunter "
        "armed with silver, kills you instead - and still goes on with their action."
    )
    abilities = (
        Ability(
            "stalk", Timing.NIGHT, "Wait outside a player's house tonight",
            params=(P.living("target", "Who to stalk"),),
            priority=Priority.STALK, leaves_house=True,
        ),
    )

    stalked: list[int] = field(default_factory=list)

    def validate(self, state: GameState, action: SubmittedAction) -> None:
        if action.target in self.stalked:
            raise GameError("You can never stalk the same player twice.")

    def interact_stalk(self, ctx: Resolution, action: SubmittedAction) -> None:
        target = ctx.target_of(action)
        ctx.commit(lambda: self.stalked.append(target))
        ctx.inform(target, "The **Shadow wolf** was waiting outside your house last night.")

        for other in ctx.actions_by(target):
            ability = ctx.ability_of(other)
            if ability is None or not ability.leaves_house or ctx.is_blocked(other):
                continue
            actor = ctx.actor_for(other)
            if actor is not None and actor.defeats_stalkers(ctx.state, other):
                victim = ctx.state.player(target)
                ctx.note("Kills", f"The Shadow wolf stalked {victim.display_name}, who was armed ({actor.name})")
                ctx.kill(self.owner, "stalked an armed player", killers=[target], killer_role=actor.name,
                         attacker_faction=victim.true_faction(), enters_house=False)
            else:
                ctx.block(other, "forced back by the Shadow wolf")
        # a stalked wolf still sets out with the pack, but is turned back
        for visit in ctx.visits:
            if visit.visitor == target and visit.pack and not visit.blocked:
                visit.blocked, visit.reason = True, "forced back by the Shadow wolf"


class ShadowWolfCommands(RoleCommands, group_name="shadow_wolf", source="shadow_wolf"):
    @app_commands.command(name="stalk", description="Wait outside a player's house tonight")
    @app_commands.describe(target="Who to stalk (never the same player twice)")
    async def stalk(self, interaction: discord.Interaction, target: discord.Member) -> None:
        await self.use(interaction, "stalk", target=target)

    @app_commands.command(name="cancel", description="Cancel tonight's stalking")
    async def cancel_stalk(self, interaction: discord.Interaction) -> None:
        await self.cancel(interaction, "stalk")
