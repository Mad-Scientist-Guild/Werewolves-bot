from Roles.role import *


@register_role
class RuthlessCounselor(Role):
    name = "ruthless_counselor"
    display = "Ruthless Counselor"
    faction = VILLAGERS
    tags = frozenset({"villager_role"})
    description = (
        "Twice per game - never two days in a row - you can call a second lynch right after the first one. All "
        "discussion and faction channels go into lockdown (private channels excepted) until its result is posted. "
        "Everyone votes again until 20:00: abstaining isn't possible, someone will die, and on a tie you decide. "
        "The Pacifist can't stop it."
    )
    abilities = (
        Ability("second_lynch", Timing.DAY, "Call a second lynch right after today's lynch",
                priority=Priority.INFO, uses=2),
    )

    def validate(self, state: GameState, action: SubmittedAction) -> None:
        if self.last_used.get("second_lynch") == state.day - 1:
            raise GameError("You can't call a second lynch two days in a row.")

    def resolve_second_lynch(self, ctx: Resolution, action: SubmittedAction) -> None:
        ctx.flags["second_lynch_by"] = self.owner
        ctx.note("Notes", "The Ruthless Counselor calls a second lynch")


class RuthlessCounselorCommands(RoleCommands, group_name="ruthless_counselor", source="ruthless_counselor"):
    @app_commands.command(name="second_lynch", description="Call a second lynch right after today's (2× per game)")
    async def second_lynch(self, interaction: discord.Interaction) -> None:
        await self.use(interaction, "second_lynch")

    @app_commands.command(name="cancel", description="Don't call a second lynch after all")
    async def cancel_second(self, interaction: discord.Interaction) -> None:
        await self.cancel(interaction, "second_lynch")
