from Roles.coven._coven import FIND, CovenCommands, CovenRole, known_members
from Roles.role import *

CURSES = {"puppet": "Curse of the Puppet", "transformation": "Curse of Transformation"}


@register_role
class Curseweaver(CovenRole):
    name = "curseweaver"
    display = "Curseweaver"
    description = (
        "Each night you can curse someone (never the same person twice in a row):\n"
        "• **Curse of the Puppet** - their night ability hits someone else, picked at random from the living "
        "(Coven members you know are left out).\n"
        "• **Curse of Transformation** - they're turned into a lizard and can't perform their night action.\n"
        "Werewolves only lose their own ability, not the pack's vote. The victim learns they were cursed the next "
        "morning. Like every Coven member you can also try to find your fellow members."
    )
    abilities = (
        FIND,
        Ability(
            "curse", Timing.NIGHT, "Curse a player tonight",
            params=(P.living("target", "Who to curse"), P.choice("curse", tuple(CURSES), "puppet or transformation")),
            priority=Priority.CURSE, leaves_house=True,
        ),
    )

    last_target: int | None = None

    def validate(self, state: GameState, action: SubmittedAction) -> None:
        super().validate(state, action)
        if action.ability == "curse" and action.target == self.last_target:
            raise GameError("You can't curse the same person twice in a row.")

    def interact_curse(self, ctx: Resolution, action: SubmittedAction) -> None:
        target = ctx.target_of(action)
        curse = action.params["curse"]
        ctx.flags[f"cursed_by:{self.owner}"] = target
        victims = [a for a in ctx.actions if a.actor == target and a.id != action.id]
        if curse == "transformation":
            for other in victims:
                ctx.block(other, "turned into a lizard (Curse of Transformation)")
        else:
            known = known_members(ctx.state, self.owner) | {self.owner}
            wheel = [p.user_id for p in ctx.state.alive_players() if p.user_id not in known and p.user_id != target]
            for other in victims:
                original = ctx.target_of(other)
                options = [w for w in wheel if w != original]
                if original is not None and options:
                    ctx.redirect(other, ctx.choice(options), reason="Curse of the Puppet")
        ctx.inform(target, f"🦎 You were cursed last night: **{CURSES[curse]}**.")
        ctx.note("Blocked" if curse == "transformation" else "Movement",
                 f"{ctx.state.name(target)} is cursed: {CURSES[curse]}")

    def after_resolution(self, ctx: Resolution) -> None:
        if ctx.kind == "night":
            self.last_target = ctx.flags.get(f"cursed_by:{self.owner}")


class CurseweaverCommands(CovenCommands, group_name="curseweaver", source="curseweaver"):
    @app_commands.command(name="curse", description="Curse a player tonight")
    @app_commands.describe(target="Who to curse", curse="Which curse")
    @app_commands.choices(curse=[app_commands.Choice(name=label, value=key) for key, label in CURSES.items()])
    async def curse(self, interaction: discord.Interaction, target: discord.Member,
                    curse: app_commands.Choice[str]) -> None:
        await self.use(interaction, "curse", target=target, curse=curse)

    @app_commands.command(name="cancel", description="Cancel tonight's curse")
    async def cancel_curse(self, interaction: discord.Interaction) -> None:
        await self.cancel(interaction, "curse")
