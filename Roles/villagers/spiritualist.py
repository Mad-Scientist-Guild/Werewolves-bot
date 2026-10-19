from datetime import datetime

from Core import realtime
from Roles.role import *


@register_role
class Spiritualist(Role):
    name = "spiritualist"
    display = "Spiritualist"
    faction = VILLAGERS
    tags = frozenset({"villager_role"})
    description = (
        "You can talk to the dead. Once a day you can ask them a yes-or-no question; you get the answer when all "
        "of them have responded, or at the end of the day (19:00) or night (00:00), whichever comes first. You "
        "learn how many said yes and no, not who. The dead may not lie. You can also talk with the Vengeful Spirit "
        "in a private chat."
    )
    abilities = (
        Ability(
            "ask", Timing.INSTANT, "Ask the dead a yes/no question (once a day)",
            params=(P.text("question", "Your yes/no question"),),
        ),
    )

    def resolve_ask(self, ctx: Resolution, action: SubmittedAction) -> None:
        question = action.params["question"]
        now = datetime.fromisoformat(action.submitted_at)
        ctx.commit(lambda: realtime.open_seance(ctx.state, self.owner, question, now))
        ctx.inform(self.owner, f"You put your question to the dead: “{question}”. The answer comes when they've all "
                               "answered, or at 19:00/00:00 at the latest.")


class SpiritualistCommands(RoleCommands, group_name="spiritualist", source="spiritualist"):
    @app_commands.command(name="ask", description="Ask the dead a yes/no question (once a day)")
    @app_commands.describe(question="Your yes/no question")
    async def ask(self, interaction: discord.Interaction, question: app_commands.Range[str, 1, 300]) -> None:
        await self.use(interaction, "ask", question=question)
