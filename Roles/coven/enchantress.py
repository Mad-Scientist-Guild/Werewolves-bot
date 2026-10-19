from datetime import datetime

from Core import realtime
from Roles.coven._coven import FIND, CovenCommands, CovenRole
from Roles.role import *

CHARMS = {
    "open_book": "Charm of the Open Book",
    "protection": "Charm of Protection",
    "revenge": "Charm of Revenge",
}
REVENGE_UNTIL_HOUR = 18


@register_role
class Enchantress(CovenRole):
    name = "enchantress"
    display = "Enchantress"
    description = (
        "Once per day you can enchant another player with one charm (it wears off the next morning; they're told "
        "they were enchanted):\n"
        "• **Open Book** - they must honestly answer a yes/no question (not about their role, ability or faction).\n"
        "• **Protection** - they can't be killed during the coming night (doesn't stop turning). Never twice on the "
        "same person.\n"
        "• **Revenge** - if they're killed during the night, the next day between 08:00 and 18:00 you may kill one "
        "player. After that you can no longer use the Charm of Protection.\n"
        "Like every Coven member you can also try to find your fellow members."
    )
    abilities = (
        FIND,
        Ability(
            "enchant", Timing.INSTANT, "Enchant a player with one of your charms (once per day)",
            params=(P.living("target", "Who to enchant"),
                    P.choice("charm", tuple(CHARMS), "open_book, protection or revenge"),
                    P.text("question", "Your yes/no question (Open Book only)", required=False)),
            phases=(Phase.DAY.value,),
        ),
        Ability(
            "revenge", Timing.INSTANT, "Unleash your revenge: kill a player",
            params=(P.living("target", "Who feels your rage"),), phases=(Phase.DAY.value,), once_per_cycle=False,
        ),
    )

    protected: list[int] = field(default_factory=list)
    revenge_day: int | None = None
    protection_lost: bool = False

    def available_abilities(self, state: GameState) -> list[Ability]:
        out = [a for a in super().available_abilities(state) if a.key != "revenge"]
        if self.revenge_day == state.day:
            out.append(self.ability("revenge"))
        return out

    def validate(self, state: GameState, action: SubmittedAction) -> None:
        super().validate(state, action)
        if action.ability == "enchant":
            charm = action.params["charm"]
            if charm == "open_book" and not action.params.get("question"):
                raise GameError("The Charm of the Open Book needs a yes/no question.")
            if charm == "protection":
                if self.protection_lost:
                    raise GameError("You can no longer use the Charm of Protection.")
                if action.target in self.protected:
                    raise GameError("You can never protect the same person twice.")
        elif action.ability == "revenge":
            if datetime.fromisoformat(action.submitted_at).hour >= REVENGE_UNTIL_HOUR:
                raise GameError("Your revenge must be taken between 08:00 and 18:00.")

    def resolve_enchant(self, ctx: Resolution, action: SubmittedAction) -> None:
        target, charm = action.params["target"], action.params["charm"]
        state = ctx.state
        expires = f"morning:{state.day + 1}"
        now = datetime.fromisoformat(action.submitted_at)
        ctx.inform(target, "✨ You have been enchanted by the **Enchantress**.")
        ctx.inform(self.owner, f"You cast the **{CHARMS[charm]}** on **{state.name(target)}**.")

        def commit() -> None:
            player = state.player(target)
            if charm == "open_book":
                realtime.ask_player(state, self.owner, target, action.params["question"], now)
            elif charm == "protection":
                add_status(state, player, "protection", source=self.owner, expires=expires,
                           label="charmed by the Enchantress", turn=False)
                self.protected.append(target)
            else:
                add_status(state, player, "enchanted_revenge", source=self.owner, expires=expires)

        ctx.commit(commit)

    def on_other_death(self, ctx: Resolution, dead: Player) -> None:
        status = dead.status("enchanted_revenge")
        if status is None or status.source != self.owner or ctx.kind != "night":
            return
        self.revenge_day = ctx.state.day + 1
        ctx.inform(self.owner, f"**{dead.display_name}**, whom you charmed with revenge, was killed. Today between "
                               "08:00 and 18:00 you may unleash your rage with `/enchantress revenge`.")

    def resolve_revenge(self, ctx: Resolution, action: SubmittedAction) -> None:
        ctx.kill(action.params["target"], "enchantress", killers=[self.owner], killer_role=self.name,
                 attacker_faction=COVEN, enters_house=False, action=action)

        def spent() -> None:
            self.revenge_day = None
            self.protection_lost = True

        ctx.commit(spent)


class EnchantressCommands(CovenCommands, group_name="enchantress", source="enchantress"):
    @app_commands.command(name="enchant", description="Enchant a player with one of your charms (once per day)")
    @app_commands.describe(target="Who to enchant", charm="Which charm", question="Your yes/no question (Open Book)")
    @app_commands.choices(charm=[app_commands.Choice(name=label, value=key) for key, label in CHARMS.items()])
    async def enchant(self, interaction: discord.Interaction, target: discord.Member,
                      charm: app_commands.Choice[str], question: str | None = None) -> None:
        await self.use(interaction, "enchant", target=target, charm=charm, question=question)

    @app_commands.command(name="revenge", description="Unleash your revenge: kill a player (08:00-18:00)")
    @app_commands.describe(target="Who feels your rage")
    async def revenge(self, interaction: discord.Interaction, target: discord.Member) -> None:
        await self.use(interaction, "revenge", target=target)
