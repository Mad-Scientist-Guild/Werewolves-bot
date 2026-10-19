import random

from Roles.role import *


@register_role
class NormalWolf(Role):
    name = "normal_wolf"
    display = "Normal wolf"
    faction = WEREWOLVES
    groups = ("wolves",)
    can_vote_wolf_kill = True
    description = (
        "You have no extra powers, but you have inside information: you know one villager role that is not in "
        "the game. Share it with the other wolves or keep it to yourself."
    )

    hint: str | None = None

    def on_game_start(self, state: GameState) -> None:
        # GMs can pick the hint beforehand: /setup role_setting normal_wolf hint <role>
        self.hint = self.setting(state, "hint", None)
        if self.hint is None:
            in_game = set(state.role_pool) | {p.role_name for p in state.players.values()}
            candidates = sorted(
                name for name, cls in ROLE_REGISTRY.items()
                if cls.faction == VILLAGERS and cls.assignable and name != "villager" and name not in in_game
            )
            if candidates:
                self.hint = random.Random(seed(state, f"normal_wolf_hint:{self.owner}")).choice(candidates)
        if self.hint is None:
            state.log("ROLE", f"No hint available for Normal wolf {state.name(self.owner)} - every villager role is "
                              "in the game. Tell them something by hand.", actor=self.owner, alert=True)
            return
        title = ROLE_REGISTRY[self.hint].title() if self.hint in ROLE_REGISTRY else self.hint
        state.emit(PrivateMessage(player=self.owner, title="🐺 Inside information",
                                  text=f"The **{title}** is not in this game."))
        state.log("ROLE", f"Normal wolf {state.name(self.owner)} learns that the {title} is not in the game.",
                  actor=self.owner)
