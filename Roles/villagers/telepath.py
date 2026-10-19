from datetime import datetime

from Core import realtime
from Roles.role import *


@register_role
class Telepath(Role):
    name = "telepath"
    display = "Telepath"
    faction = VILLAGERS
    tags = frozenset({"villager_role"})
    description = (
        "Once a day (08:00-00:00) you can send an anonymous message of at most 20 words to a living player. They "
        "receive exactly your message through a Game Master and can send one reply (also 20 words at most)."
    )
    abilities = (
        Ability(
            "send", Timing.INSTANT, "Send an anonymous message (max 20 words) to a living player",
            params=(P.living("target", "Who receives your message"),
                    P.text("message", "Your message (max 20 words)", max_words=realtime.MAX_WORDS)),
            phases=(Phase.DAY.value, Phase.NIGHT.value),
        ),
    )

    def resolve_send(self, ctx: Resolution, action: SubmittedAction) -> None:
        target, text = action.params["target"], action.params["message"]
        now = datetime.fromisoformat(action.submitted_at)
        ctx.commit(lambda: realtime.send_telepathy(ctx.state, self.owner, target, text, now))
        ctx.inform(self.owner, f"Your message reached **{ctx.state.name(target)}**. If they answer, you'll hear it here.")


class TelepathCommands(RoleCommands, group_name="telepath", source="telepath"):
    @app_commands.command(name="send", description="Send an anonymous message (max 20 words) - once a day")
    @app_commands.describe(target="Who receives it", message="Max 20 words")
    async def send(self, interaction: discord.Interaction, target: discord.Member,
                   message: app_commands.Range[str, 1, 300]) -> None:
        await self.use(interaction, "send", target=target, message=message)
