from Core.actor import role_class
from Roles.role import *

# villager roles the Actor can't take on (they make no sense for a day)
NOT_COPYABLE = frozenset({"actor", "villager", "adopted_child", "brother", "grave_robber", "cupid"})


@register_role
class TheActor(Role):
    name = "actor"
    display = "Actor"
    faction = VILLAGERS
    tags = frozenset({"villager_role"})
    description = (
        "Once per day you can take on another villager role: for that day and the following night you have its "
        "powers (with fresh uses) and can use its commands. You can never take on the same role twice, and not "
        "the Adopted Child, a Brother, the Grave Robber or Cupid. A copied Spiritualist doesn't get the Vengeful "
        "Spirit's chat, a copied Monster Hunter has no silver."
    )
    abilities = (
        Ability(
            "copy", Timing.INSTANT, "Take on another villager role for today and tonight",
            params=(P.role("role", "The villager role to take on"),), phases=(Phase.DAY.value,),
        ),
    )

    copied: list[str] = field(default_factory=list)
    current: Role | None = None        # the role being played right now
    current_day: int = 0

    # --- the copy ----------------------------------------------------------------
    def playing(self, state: GameState) -> Role | None:
        """The copied role, if it's still the same day/night."""
        return self.current if self.current is not None and self.current_day == state.day else None

    def provides(self, source: str) -> bool:
        return source == self.name or (self.current is not None and self.current.name == source)

    def available_abilities(self, state: GameState) -> list[Ability]:
        own = [a for a in self.abilities if self.last_used.get(a.key) != state.day]
        copy = self.playing(state)
        return own + (copy.available_abilities(state) if copy is not None else [])

    def command_source(self, ability_key: str) -> str:
        copy = self._copy_for(ability_key)
        return copy.name if copy is not None else self.name

    def ability(self, key: str) -> Ability | None:
        own = super().ability(key)
        if own is not None or self.current is None:
            return own
        return self.current.ability(key)

    def _copy_for(self, key: str) -> Role | None:
        if super().ability(key) is None and self.current is not None and self.current.ability(key) is not None:
            return self.current
        return None

    def uses_left(self, state: GameState, ability: Ability) -> int | None:
        copy = self._copy_for(ability.key)
        return copy.uses_left(state, ability) if copy is not None else super().uses_left(state, ability)

    def consume(self, state: GameState, ability_key: str) -> None:
        copy = self._copy_for(ability_key)
        (copy if copy is not None else super()).consume(state, ability_key)

    def refund(self, ability_key: str) -> None:
        copy = self._copy_for(ability_key)
        (copy if copy is not None else super()).refund(ability_key)

    def __getattr__(self, name: str):
        # resolve_<ability> / interact_<ability> of the copied role
        if name.startswith(("resolve_", "interact_")):
            current = self.__dict__.get("current")
            if current is not None and hasattr(current, name):
                return getattr(current, name)
        raise AttributeError(name)

    # hooks of the copied role keep working while it's being played
    def protects_against(self, ctx: Resolution, kill: Kill) -> str | None:
        copy = self.playing(ctx.state)
        return copy.protects_against(ctx, kill) if copy else None

    def defeats_stalkers(self, state: GameState, action: SubmittedAction) -> bool:
        copy = self.playing(state)
        return copy.defeats_stalkers(state, action) if copy else False

    def on_kill_prevented(self, ctx: Resolution, kill: Kill) -> None:
        if (copy := self.playing(ctx.state)) is not None:
            copy.on_kill_prevented(ctx, kill)

    def on_other_killed(self, ctx: Resolution, kill: Kill) -> None:
        if (copy := self.playing(ctx.state)) is not None:
            copy.on_other_killed(ctx, kill)

    def on_other_converted(self, ctx: Resolution, player: Player, kind: str, by: int) -> None:
        if (copy := self.playing(ctx.state)) is not None:
            copy.on_other_converted(ctx, player, kind, by)

    def after_resolution(self, ctx: Resolution) -> None:
        if (copy := self.playing(ctx.state)) is not None:
            copy.after_resolution(ctx)

    # --- taking on a role --------------------------------------------------------------
    def validate(self, state: GameState, action: SubmittedAction) -> None:
        if action.ability != "copy":
            copy = self.playing(state)
            if copy is not None:
                copy.validate(state, action)
            return
        role = action.params["role"]
        cls = role_class(role)
        if cls.faction != VILLAGERS or not cls.assignable or role in NOT_COPYABLE:
            raise GameError(f"You can't take on the {cls.title()}.")
        if role in self.copied:
            raise GameError(f"You've already played the {cls.title()} - never the same role twice.")

    def resolve_copy(self, ctx: Resolution, action: SubmittedAction) -> None:
        role = action.params["role"]
        cls = role_class(role)

        def commit() -> None:
            self.current = cls(owner=self.owner)
            self.current_day = ctx.state.day
            self.copied.append(role)
            ctx.state.emit(RoleCard(player=self.owner, role=role, changed=True,
                                    note="🎭 You're the Actor: you play this role today and tonight only."))

        ctx.commit(commit)
        ctx.note("Conversions", f"The Actor {ctx.state.name(self.owner)} plays the {cls.title()} today")


class ActorCommands(RoleCommands, group_name="actor", source="actor"):
    @app_commands.command(name="copy", description="Take on another villager role for today and tonight")
    @app_commands.describe(role="The villager role to play")
    @app_commands.autocomplete(role=role_autocomplete)
    async def copy(self, interaction: discord.Interaction, role: str) -> None:
        await self.use(interaction, "copy", role=role)
