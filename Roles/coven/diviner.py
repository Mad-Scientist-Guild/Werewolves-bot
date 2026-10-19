from datetime import datetime

from Core import realtime
from Core.actions import pending_action
from Roles.coven._coven import FIND, CovenCommands, CovenRole, known_members
from Roles.role import *


@register_role
class Diviner(CovenRole):
    name = "diviner"
    display = "Diviner"
    description = (
        "Each night you can divine a house (a family) in one of three ways:\n"
        "• **Detection** - learn one person who left that house during the night.\n"
        "• **Vision** - learn one role living in that house.\n"
        "• **Scrying** - pick a 60-minute window (in the future) to listen in on that family's chat: you get the "
        "first 15 minutes of conversation from the moment someone talks, speakers numbered, names they mention "
        "visible.\n"
        "Coven members you know are never picked for Detection or Vision. Like every Coven member you can also try "
        "to find your fellow members."
    )
    abilities = (
        FIND,
        Ability(
            "divine", Timing.NIGHT, "Divine a house tonight: Detection or Vision",
            params=(P.living("target", "Someone who lives in the house", allow_self=True),
                    P.choice("method", ("detection", "vision"), "detection or vision")),
            priority=Priority.INFO,
        ),
        Ability(
            "scry", Timing.INSTANT, "Listen in on a house's family chat for an hour (instead of divining tonight)",
            params=(P.living("target", "Someone who lives in the house", allow_self=True),
                    P.time("start", "When your hour starts (HH:MM)")),
            phases=(Phase.NIGHT.value,),
        ),
    )

    scry_nights: list[int] = field(default_factory=list)

    def validate(self, state: GameState, action: SubmittedAction) -> None:
        super().validate(state, action)
        if action.ability in ("divine", "scry") and state.day in self.scry_nights:
            raise GameError("You've already used your divination tonight (scrying).")
        if action.ability == "scry":
            if pending_action(state, self.owner, "divine", self.name) is not None:
                raise GameError("You've already chosen to divine tonight - cancel that first.")
            if state.player(action.target).family is None:
                raise GameError("That player doesn't live with a family - there's no chat to listen in on.")

    def resolve_divine(self, ctx: Resolution, action: SubmittedAction) -> None:
        target = ctx.target_of(action)
        known = known_members(ctx.state, self.owner) | {self.owner}
        house = [p for p in ctx.state.housemates(target) if p.user_id not in known]
        where = f"the house of **{ctx.state.name(target)}**"
        if action.params["method"] == "detection":
            out = [p.user_id for p in house if ctx.left_house(p.user_id)]
            if out:
                ctx.inform(self.owner, f"Detection: **{ctx.state.name(ctx.choice(out))}** left {where} last night.")
            else:
                ctx.inform(self.owner, f"Detection: nothing happened at {where} - nobody left.")
            return
        living = [p.user_id for p in house if p.alive]
        if not living:
            ctx.inform(self.owner, f"Vision: you saw nothing in {where}.")
            return
        seen = ctx.state.player(ctx.choice(living))
        role = ROLE_REGISTRY[seen.role_name].title() if seen.role_name in ROLE_REGISTRY else seen.role_name
        ctx.inform(self.owner, f"Vision: someone living in {where} is the **{role}**.")

    def resolve_scry(self, ctx: Resolution, action: SubmittedAction) -> None:
        now = datetime.fromisoformat(action.submitted_at)
        start = realtime.next_occurrence(ctx.state, action.params["start"], now)
        family = ctx.state.player(action.target).family

        def commit() -> None:
            realtime.schedule_relay(ctx.state, self.owner, family, start, purpose="diviner", now=now)
            self.scry_nights.append(ctx.state.day)

        ctx.commit(commit)
        ctx.inform(self.owner, f"You'll scry the house of **{ctx.state.name(action.target)}** from {start:%H:%M}.")


class DivinerCommands(CovenCommands, group_name="diviner", source="diviner"):
    @app_commands.command(name="divine", description="Divine a house tonight: Detection or Vision")
    @app_commands.describe(target="Someone who lives in the house", method="What to divine")
    @app_commands.choices(method=[app_commands.Choice(name="Detection - who left the house", value="detection"),
                                  app_commands.Choice(name="Vision - a role living there", value="vision")])
    async def divine(self, interaction: discord.Interaction, target: discord.Member,
                     method: app_commands.Choice[str]) -> None:
        await self.use(interaction, "divine", target=target, method=method)

    @app_commands.command(name="scry", description="Listen in on a family's chat for an hour (instead of divining)")
    @app_commands.describe(target="Someone who lives in the house", start="HH:MM (24-hour), in the future")
    async def scry(self, interaction: discord.Interaction, target: discord.Member, start: str) -> None:
        await self.use(interaction, "scry", target=target, start=start)

    @app_commands.command(name="cancel", description="Cancel tonight's divination")
    async def cancel_divine(self, interaction: discord.Interaction) -> None:
        await self.cancel(interaction, "divine")
