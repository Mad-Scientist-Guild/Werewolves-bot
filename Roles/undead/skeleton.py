from Core.resolution import register_conversion
from Roles.role import *


@register_modifier
class Skeleton(Modifier):
    """Acquired: a dead player raised by the Lich (or a Gambler who visited the Lich)."""
    name = "skeleton"
    display = "Skeleton"
    description = (
        "You've been raised from the dead to serve the Lich. You're back in the village chat, but you may only "
        "react (default and Werewolves emotes only - and don't spell words with letters!). You can't vote, and "
        "you can no longer see the dead chat, though you may share what you learned there. You share a chat with "
        "the Lich and the other skeletons. If the Lich dies, so do you - and a Skeleton never rises again."
    )
    true_faction = UNDEAD
    public_status = PublicStatus.SKELETON

    lich: int | None = None


def raise_skeleton(ctx: Resolution, target: int, by: int) -> None:
    """The "skeleton" conversion (commit pass)."""
    state = ctx.state
    player = state.player(target)
    if player.life is not LifeState.DEAD:
        ctx.note("Conversions", f"{player.display_name} can't be raised ({player.life.value})")
        return
    player.life = LifeState.SKELETON
    spirit = player.modifier("vengeful_spirit")
    if spirit is not None and getattr(spirit, "active", False):
        spirit.move_on(ctx, "raised as a skeleton")
    add_modifier(state, player, "skeleton", reason=f"raised by {state.name(by)}", lich=by)
    group = state.ensure_group(f"skeletons:{by}", GroupKind.SKELETONS, "skeletons")
    group.add(by)
    group.add(target)
    ctx.inform(target, "💀 You rise from your grave as a **Skeleton**, serving the Lich. You can react in the village "
                       "chat again, and you share a chat with the Lich.")
    ctx.note("Conversions", f"{player.display_name} rises as a Skeleton (Lich: {state.name(by)})")


register_conversion("skeleton", raise_skeleton)
