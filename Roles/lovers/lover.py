from Roles.role import *
from Roles.modifiers.vengeful_spirit import make_vengeful_spirit

# modifiers that mean a lover was "turned": they no longer die of heartbreak
TURNED_MODIFIERS = ("turned_wolf", "vampire_spawn", "changeling")


def turned(player: Player) -> bool:
    # a Changeling only "turns out to be" one once it has grown up into a hybrid
    return any(m.name in TURNED_MODIFIERS and (m.name != "changeling" or getattr(m, "grown", False))
               for m in player.modifiers)


def turned_by(player: Player) -> int | None:
    for modifier in reversed(player.modifiers):
        if modifier.name in TURNED_MODIFIERS:
            return getattr(modifier, "turned_by", None)
    return None


@register_modifier
class Lover(Modifier):
    """Acquired on the first night through Cupid's arrow."""
    name = "lover"
    display = "Lover"
    description = (
        "Cupid's arrow struck you. You and your lover share a chat and want to survive together, whoever else "
        "wins. If your lover dies, you die of a broken heart."
    )

    partner: int = 0
    cupid: int | None = None
    bond_broken: bool = False   # the lovers' win condition no longer applies (a lover was turned / revived)

    def faction_override(self, player: Player) -> str | None:
        # a turned lover belongs to whoever turned them, whatever happened first
        return None if self.bond_broken or turned(player) else LOVERS

    def on_other_death(self, ctx: Resolution, dead: Player) -> None:
        if dead.user_id != self.partner:
            return
        me = self.player(ctx.state)
        if not me.alive:
            return
        if turned(me):
            ctx.note("Deaths", f"{me.display_name} doesn't die of heartbreak - they were turned")
            return
        ctx.kill(self.owner, "heartbreak", killers=[dead.user_id], killer_role="heartbreak", unstoppable=True,
                 enters_house=False)

    def on_death(self, ctx: Resolution, record: DeathRecord) -> None:
        partner = ctx.state.find_player(self.partner)
        if partner is None:
            return
        me = self.player(ctx.state)
        if partner.alive and turned(partner):
            # they died, but their turned partner lives on
            turner = turned_by(partner)
            make_vengeful_spirit(ctx, me, allowed=[turner] if turner else [], any_werewolf=False,
                                 reason=f"their lover {partner.display_name} was turned")
            return
        cheating = ctx.flags.get(f"slut_cheating_death:{self.partner}")
        if record.cause == "heartbreak" and cheating is not None and cheating != self.owner:
            # betrayed: their lover, the Village Slut, died while spending the night with someone else
            slut_death = partner.death
            make_vengeful_spirit(ctx, me, allowed=list(slut_death.killer_ids) if slut_death else [],
                                 any_werewolf=bool(slut_death and slut_death.killer_role == "werewolves"),
                                 reason="betrayed by their lover, the Village Slut")

    def on_other_converted(self, ctx: Resolution, player: Player, kind: str, by: int) -> None:
        if player.user_id == self.partner and not self.bond_broken:
            self.bond_broken = True
            ctx.note("Conversions", f"The lovers' bond of {ctx.state.name(self.owner)} is broken: their partner "
                                    "was turned (they still die of heartbreak if the partner dies)")

    def on_revived(self, ctx: Resolution) -> None:
        self.bond_broken = True
        ctx.inform(self.owner, "You've come back to life - your heart is your own again: you're aligned with your "
                               "original faction, not with the Lovers.")
