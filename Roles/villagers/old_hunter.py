from Roles.role import *


@register_role
class OldHunter(Role):
    name = "old_hunter"
    display = "Old Hunter"
    faction = VILLAGERS
    description = (
        "Once a night you can coat your sword in wolfsbane (your stash lasts 3 nights). If werewolves attack you - "
        "or try to turn you - while your sword is coated, you survive and one of the attacking wolves dies the next "
        "morning. If they attack while it isn't coated, you die. You can only kill werewolves this way. "
        "(Coating doesn't make you leave the house, so wolves who only track or stalk you are safe.)"
    )
    abilities = (
        Ability("coat", Timing.NIGHT, "Coat your sword in wolfsbane tonight", priority=Priority.PROTECT, uses=3),
    )

    def interact_coat(self, ctx: Resolution, action: SubmittedAction) -> None:
        # first, so the wolfsbane triggers even when someone else also protects the Old Hunter
        ctx.protect(self.owner, "wolfsbane", lambda attack: attack.attacker_faction == WEREWOLVES, first=True)

    def on_attack_prevented(self, ctx: Resolution, attack: Attack) -> None:
        if attack.prevented_by != "wolfsbane":
            return
        wolves = [w for w in attack.killers if ctx.state.player(w).alive]
        if not wolves:
            return
        victim = ctx.choice(wolves)
        ctx.attack(victim, "wolfsbane", killers=[self.owner], killer_role=self.name, attacker_faction=VILLAGERS,
                 enters_house=False)
        ctx.inform(self.owner, "The werewolves came for you, but your sword was coated in wolfsbane. One of them "
                               "won't see another morning.")
        ctx.newspaper(f"A werewolf ({ctx.state.name(victim)}) was killed by the Old Hunter's wolfsbane.")


class OldHunterCommands(RoleCommands, CancelCommand, group_name="old_hunter", source="old_hunter"):
    @app_commands.command(name="coat", description="Coat your sword in wolfsbane tonight (3× per game)")
    async def coat(self, interaction: discord.Interaction) -> None:
        await self.use(interaction, "coat")
