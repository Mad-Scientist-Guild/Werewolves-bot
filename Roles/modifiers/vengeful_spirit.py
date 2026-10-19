from Core.resolution import register_final_hook
from Roles.role import *

NIGHTS = 3


@register_modifier
class VengefulSpirit(Modifier):
    """The first player(s) to die - and some lovers - come back as a Vengeful Spirit."""
    name = "vengeful_spirit"
    display = "Vengeful Spirit"
    description = (
        "Dying first is just bad - and it made you angry. You can talk with the Spiritualist in a private chat "
        "(not with the other dead). Within three nights you may name who - or what - killed you, once: if you're "
        "right, they die. Killed by the werewolf pack? Any werewolf will do. Either way, after your guess or the "
        "three nights you move on to the afterlife."
    )
    abilities = (
        Ability(
            "avenge", Timing.NIGHT, "Name who killed you - if you're right, they die",
            params=(P.living("target", "Your killer"),), priority=Priority.KILL, usable_while_dead=True, uses=1,
        ),
    )

    active: bool = True
    allowed: list[int] = field(default_factory=list)   # the right answers
    any_werewolf: bool = False                          # killed by the pack: any werewolf is right
    nights_seen: int = 0
    since: str = ""                                     # resolution slot in which they became a spirit
    spirit_group: str | None = None

    # while active they carry the public Vengeful Spirit role and are kept out of the dead chat
    @property
    def public_status(self) -> PublicStatus | None:   # type: ignore[override]
        return PublicStatus.VENGEFUL_SPIRIT if self.active else None

    @property
    def blocks_dead_chat(self) -> bool:   # type: ignore[override]
        return self.active

    def available_abilities(self, state: GameState) -> list[Ability]:
        return super().available_abilities(state) if self.active else []

    def resolve_avenge(self, ctx: Resolution, action: SubmittedAction) -> None:
        target = ctx.state.player(ctx.target_of(action))
        right = target.user_id in self.allowed or (self.any_werewolf and target.can_vote_wolf_kill())
        if right:
            ctx.kill(target.user_id, "vengeful_spirit", killers=[self.owner], killer_role=self.name,
                     enters_house=False, action=action)
            ctx.inform(self.owner, f"You were right: **{target.display_name}** feels your vengeance.")
        else:
            ctx.inform(self.owner, f"**{target.display_name}** wasn't your killer. Your anger fades.")
        ctx.commit(lambda: self.move_on(ctx, "made their guess"))

    def after_resolution(self, ctx: Resolution) -> None:
        if ctx.kind != "night" or not self.active or self.since == ctx.slot:
            return
        self.nights_seen += 1
        if self.nights_seen >= self.setting(ctx.state, "nights", NIGHTS):
            ctx.inform(self.owner, "Your nights of vengeance are over.")
            self.move_on(ctx, "their nights ran out")

    def move_on(self, ctx: Resolution, reason: str) -> None:
        if not self.active:
            return
        self.active = False
        if self.spirit_group and self.spirit_group in ctx.state.groups:
            ctx.state.groups[self.spirit_group].leave(self.owner)
        ctx.inform(self.owner, "You move on to the afterlife and join the other dead.")
        ctx.note("Deaths", f"Vengeful Spirit {ctx.state.name(self.owner)} moves on ({reason})")


def make_vengeful_spirit(ctx: Resolution, player: Player, *, allowed: list[int], any_werewolf: bool,
                         reason: str) -> None:
    """Turn a dead player into a Vengeful Spirit (commit pass)."""
    if player.has_modifier("vengeful_spirit"):
        return
    state = ctx.state
    spirit = add_modifier(state, player, "vengeful_spirit", reason=reason, allowed=allowed,
                          any_werewolf=any_werewolf, since=ctx.slot)
    group = state.ensure_group(f"spirit:{player.user_id}", GroupKind.SPIRIT_LINE, "vengeful-spirit")
    group.add(player.user_id)
    for spiritualist in state.players_with_role("spiritualist", alive_only=True):
        group.add(spiritualist.user_id)
    spirit.spirit_group = group.key
    ctx.inform(player.user_id, "👻 You are a **Vengeful Spirit**! You can talk with the Spiritualist in your spirit "
                               "chat, and within three nights you may name your killer with "
                               "`/vengeful_spirit avenge` - if you're right, they die.")
    ctx.note("Deaths", f"{player.display_name} becomes a Vengeful Spirit ({reason})")


@register_final_hook
def first_deaths_become_spirits(ctx: Resolution) -> None:
    """Everyone in the first batch of deaths becomes a Vengeful Spirit (GM kills don't count)."""
    if ctx.state.data.get("first_death_seen"):
        return
    deaths = [(p, r) for p, r in ctx.deaths if r.killer_role != "gm"]
    if not deaths:
        return
    ctx.state.data["first_death_seen"] = True
    for player, record in deaths:
        make_vengeful_spirit(ctx, player, allowed=list(record.killer_ids),
                             any_werewolf=record.killer_role == "werewolves", reason="among the first to die")


class VengefulSpiritCommands(RoleCommands, group_name="vengeful_spirit", source="vengeful_spirit"):
    @app_commands.command(name="avenge", description="Name who killed you (once) - if you're right, they die")
    @app_commands.describe(target="Your killer")
    async def avenge(self, interaction: discord.Interaction, target: discord.Member) -> None:
        await self.use(interaction, "avenge", target=target)

    @app_commands.command(name="cancel", description="Take back tonight's guess")
    async def cancel_avenge(self, interaction: discord.Interaction) -> None:
        await self.cancel(interaction, "avenge")
