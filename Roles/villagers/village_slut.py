from Roles.role import *

TURNED_ALONG = {"werewolf": WEREWOLVES, "vampire": UNDEAD}


@register_role
class VillageSlut(Role):
    name = "village_slut"
    display = "Village Slut"
    faction = VILLAGERS
    tags = frozenset({"villager_role"})
    description = (
        "Every night you can spend the night at someone else's house. If anyone attacks you at home, you're not "
        "there and survive. But if your host is attacked, you die with them - and if your host is turned into a "
        "werewolf or vampire, you're turned too. You learn whether your host left the house that night, and if "
        "you visit the Insomniac you learn each other's roles."
    )
    abilities = (
        Ability(
            "visit", Timing.NIGHT, "Spend the night at someone else's house",
            params=(P.living("target", "Who to spend the night with"),),
            priority=Priority.PROTECT, leaves_house=True,
        ),
    )

    def _host(self, ctx: Resolution) -> int | None:
        return ctx.flags.get(f"slut_host:{self.owner}")

    def interact_visit(self, ctx: Resolution, action: SubmittedAction) -> None:
        # runs after locks and stalks, so only when the Slut really got out
        ctx.flags[f"slut_host:{self.owner}"] = ctx.target_of(action)
        ctx.protect(self.owner, "not home (spending the night elsewhere)", lambda kill: kill.enters_house)

    def resolve_visit(self, ctx: Resolution, action: SubmittedAction) -> None:
        host = ctx.state.player(self._host(ctx))
        went = "left their house" if ctx.left_house(host.user_id) else "stayed at home"
        ctx.inform(self.owner, f"You spent the night with **{host.display_name}**, who {went} during the night.")
        if host.role_name == "insomniac":
            ctx.inform(self.owner, f"{host.display_name} couldn't sleep - they are the **Insomniac**.")
            ctx.inform(host.user_id, f"You had company tonight: **{ctx.state.name(self.owner)}** is the **Village Slut**.")

    def on_other_killed(self, ctx: Resolution, kill: Kill) -> None:
        # Any attack on the host (anything that enters the house) kills the Slut too.
        # Heartbreak, guilt etc. aren't attacks: they don't enter the house.
        if kill.target != self._host(ctx) or not kill.enters_house:
            return
        ctx.note("Kills", f"The Village Slut {ctx.state.name(self.owner)} was with {ctx.state.name(kill.target)}")
        ctx.flags[f"slut_cheating_death:{self.owner}"] = kill.target   # a betrayed lover becomes a Vengeful Spirit
        ctx.kill(self.owner, kill.cause, killers=kill.killers, killer_role=kill.killer_role,
                 attacker_faction=kill.attacker_faction, enters_house=False)

    def on_other_converted(self, ctx: Resolution, player: Player, kind: str, by: int) -> None:
        # Werewolf and vampire turning are attacks on the host's house, so the Slut is
        # turned along with the host. Changeling turning is NOT: the Hag Mother picks
        # one person to secretly become her Changeling - nothing happens at the house,
        # so a visiting Slut isn't caught up in it.
        if player.user_id != self._host(ctx) or kind not in TURNED_ALONG:
            return
        # she's caught at the host's house, so her own "not home" doesn't help her here
        if ctx.turn_prevented(self.owner, attacker_faction=TURNED_ALONG[kind], killers=[by], enters_house=False):
            return
        ctx.note("Conversions", f"The Village Slut {ctx.state.name(self.owner)} is turned along with "
                                f"{player.display_name}")
        ctx.convert(kind, self.owner, by=by)


class VillageSlutCommands(RoleCommands, group_name="village_slut", source="village_slut"):
    @app_commands.command(name="visit", description="Spend the night at someone else's house")
    @app_commands.describe(target="Who to spend the night with")
    async def visit(self, interaction: discord.Interaction, target: discord.Member) -> None:
        await self.use(interaction, "visit", target=target)

    @app_commands.command(name="cancel", description="Stay home tonight after all")
    async def cancel_visit(self, interaction: discord.Interaction) -> None:
        await self.cancel(interaction, "visit")
