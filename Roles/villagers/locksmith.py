from Roles.role import *


@register_role
class Locksmith(Role):
    name = "locksmith"
    display = "Locksmith"
    faction = VILLAGERS
    tags = frozenset({"villager_role"})
    description = (
        "Once a night you can lock someone's house (a house is a whole family; your own is allowed). Nobody can "
        "enter a locked house - not Villagers, Werewolves, Undead or Coven - and nobody inside can use powers that "
        "make them leave the house. You can never lock the same person's house twice."
    )
    abilities = (
        Ability(
            "lock", Timing.NIGHT, "Lock a player's house (their whole family) for the night",
            params=(P.living("target", "Whose house to lock", allow_self=True),),
            priority=Priority.LOCK, leaves_house=True,
        ),
    )

    locked: list[int] = field(default_factory=list)

    def validate(self, state: GameState, action: SubmittedAction) -> None:
        if action.target in self.locked:
            raise GameError("You can never lock the same person's house twice.")

    def interact_lock(self, ctx: Resolution, action: SubmittedAction) -> None:
        target = ctx.target_of(action)
        house = ctx.state.house_of(target)
        members = {p.user_id for p in ctx.state.house_members(house)}
        label = ctx.state.groups[house].name if house in ctx.state.groups else ctx.state.name(target)
        ctx.note("Protections", f"The house of {label} is locked")
        ctx.commit(lambda: self.locked.append(target))
        for member in members:
            ctx.protect(member, "the house was locked", lambda kill: kill.enters_house)
        for visit in ctx.visits:
            if visit.action_id == action.id or visit.blocked:
                continue
            if visit.visitor in members:
                reason = "locked in by the Locksmith"
            elif visit.target in members:
                reason = "the house was locked"
            else:
                continue
            other = ctx.action_by_id(visit.action_id)
            if other is not None:
                ctx.block(other, reason)
            else:   # the werewolf pack's attack
                visit.blocked, visit.reason = True, reason


class LocksmithCommands(RoleCommands, group_name="locksmith", source="locksmith"):
    @app_commands.command(name="lock", description="Lock a player's house (their whole family) tonight")
    @app_commands.describe(target="Whose house to lock (yours is allowed)")
    async def lock(self, interaction: discord.Interaction, target: discord.Member) -> None:
        await self.use(interaction, "lock", target=target)

    @app_commands.command(name="cancel", description="Cancel tonight's lock")
    async def cancel_lock(self, interaction: discord.Interaction) -> None:
        await self.cancel(interaction, "lock")
