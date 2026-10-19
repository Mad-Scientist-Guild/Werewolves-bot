"""The werewolf pack: the nightly group vote and the attack it produces.

Every actor with `can_vote_wolf_kill = True` (wolf roles, the Turned wolf
modifier...) takes part. A victim needs votes from more than half of the
eligible pack; wolves who don't vote count as abstaining; anything else,
ties included, means nobody is eaten. When the pack kills, every living
pack wolf counts as attacking (leaves the house, can be trapped...).
"""
from Core import voting
from Core.clock import now_in
from Core.effects import GroupMessage
from Core.resolution import register_prepare_hook
from Core.state import Phase
from Roles.role import *
from Services.discord_utils import reply
from Services.runtime import runtime

PACK_SOURCE = "werewolves"


@register_prepare_hook
def wolf_pack_attack(ctx: Resolution) -> None:
    if ctx.kind != "night":
        return
    ballot = ctx.state.ballots.get(voting.WOLVES)
    if ballot is None or ballot.day != ctx.state.day:
        return
    tally = voting.tally_wolves(ctx.state, ballot)
    ctx.flags["pack_tally"] = tally
    ctx.note("Actions", f"Werewolf vote: {voting.describe_counts(ctx.state, tally)} → {tally.outcome}"
                        + (f" ({ctx.state.name(tally.target)})" if tally.target else ""))
    if tally.outcome != "kill":
        return
    # the whole living pack attacks (and leaves the house), not just the wolves who voted for the victim
    attackers = sorted(p.user_id for p in voting.eligible_voters(ctx.state, voting.WOLVES))
    ctx.flags["pack_target"] = tally.target
    ctx.flags["pack_attackers"] = attackers
    for wolf in attackers:
        ctx.visits.append(Visit(visitor=wolf, target=tally.target, action_id=None, source=PACK_SOURCE,
                                ability="attack", pack=True))
    ctx.flags["pack_kill"] = ctx.kill(
        tally.target, "werewolves", killers=attackers, killer_role="werewolves", attacker_faction=WEREWOLVES,
    )


def pack_summary(state: GameState) -> str:
    ballot = state.ballots.get(voting.WOLVES)
    if ballot is None:
        return "No werewolf vote is open."
    tally = voting.tally_wolves(state, ballot)
    needed = tally.eligible // 2 + 1
    return f"{voting.describe_counts(state, tally)} — a victim needs {needed} of {tally.eligible} votes."


class WolvesCommands(RoleCommands, group_name="wolves", source=PACK_SOURCE):
    @app_commands.command(name="vote", description="Vote for who the pack eats tonight")
    @app_commands.describe(target="Who to eat")
    async def vote(self, interaction: discord.Interaction, target: discord.Member) -> None:
        await self._cast(interaction, target.id)

    @app_commands.command(name="abstain", description="Vote for the pack to eat nobody tonight")
    async def abstain(self, interaction: discord.Interaction) -> None:
        await self._cast(interaction, None)

    @app_commands.command(name="status", description="See the pack's votes so far")
    async def status(self, interaction: discord.Interaction) -> None:
        state = runtime.games.get(interaction.guild_id).state
        player = state.player(interaction.user.id)
        if not player.can_vote_wolf_kill():
            raise GameError("You're not part of the werewolf pack.")
        ballot = state.ballots.get(voting.WOLVES)
        votes = voting.published_votes(state, ballot) if ballot else ""
        await reply(interaction, f"{pack_summary(state)}\n{votes}")

    async def _cast(self, interaction: discord.Interaction, target: int | None) -> None:
        async with runtime.games.mutate(interaction.guild_id) as state:
            if state.phase is not Phase.NIGHT:
                raise GameError("The pack can only vote at night (19:00-00:00).")
            voting.cast_vote(state, voting.WOLVES, interaction.user.id, target, at=now_in(state).isoformat())
            voter = state.name(interaction.user.id)
            choice = f"votes to eat **{state.name(target)}**" if target else "votes to eat nobody"
            summary = pack_summary(state)
            state.log("WOLVES", f"{voter} {choice}. {summary}", actor=interaction.user.id,
                      targets=[target] if target else [])
            state.emit(GroupMessage(group="wolves", text=f"**{voter}** {choice}.\n{summary}"))
        await reply(interaction, f"Your vote is in. {summary}")
