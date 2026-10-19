from Core.effects import GroupMessage
from Roles.role import *

register_group("brothers", GroupKind.BROTHERS, "brothers")


@register_role
class Brother(Role):
    name = "brother"
    display = "Brother"
    faction = VILLAGERS
    tags = frozenset({"villager_role"})
    groups = ("brothers",)
    description = (
        "The bond of Brothers transcends family. All Brothers share a private chat, so you know each other's role "
        "and can plan together. At any time the Brothers can unanimously add someone else to the chat - their role "
        "isn't revealed to you. Every living Brother has to propose the same person with `/brother invite`."
    )
    abilities = (
        Ability(
            "invite", Timing.INSTANT, "Propose adding someone to the Brothers' chat (every Brother must agree)",
            params=(P.living("target", "Who to welcome into the brotherhood"),),
            once_per_cycle=False, first_day=True,
        ),
    )

    def validate(self, state: GameState, action: SubmittedAction) -> None:
        group = state.groups.get("brothers")
        if group is not None and action.target in group.active_members():
            raise GameError(f"{state.name(action.target)} is already in the Brothers' chat.")

    def resolve_invite(self, ctx: Resolution, action: SubmittedAction) -> None:
        state = ctx.state
        target = state.player(action.target)

        def commit() -> None:
            invites = state.data.setdefault("brother_invites", {})
            agreed = set(invites.get(str(target.user_id), [])) | {self.owner}
            brothers = {p.user_id for p in state.alive_players() if p.role_name == self.name}
            if brothers <= agreed:
                invites.pop(str(target.user_id), None)
                join_group(state, target, "brothers")
                state.emit(GroupMessage(group="brothers", text=f"**{target.display_name}** has joined the brotherhood."))
                ctx.inform(target.user_id, "🤝 The Brothers have welcomed you into their chat.")
            else:
                invites[str(target.user_id)] = sorted(agreed)
                state.emit(GroupMessage(group="brothers", text=(
                    f"**{state.name(self.owner)}** proposes adding **{target.display_name}** "
                    f"({len(agreed & brothers)}/{len(brothers)} Brothers agree). Agree with `/brother invite`.")))

        ctx.commit(commit)


class BrotherCommands(RoleCommands, group_name="brother", source="brother"):
    @app_commands.command(name="invite", description="Propose adding someone to the Brothers' chat")
    @app_commands.describe(target="Who to welcome (every living Brother must propose them)")
    async def invite(self, interaction: discord.Interaction, target: discord.Member) -> None:
        await self.use(interaction, "invite", target=target)
