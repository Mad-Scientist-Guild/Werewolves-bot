from Roles.role import *

# TODO(adopted child): automate joining the second family. Open design question (GM, Oct 2026):
# a house is a family, but the Adopted Child belongs to two families - it isn't decided yet how
# that works for houses (Locksmith locks, Priest blessings, the Insomniac, the Diviner, visits...).
# Until then the GMs add the Adopted Child to their second family's chat by hand:
#   /gm group add <player> family:<n>
# and tell that family who the Adopted Child is.


@register_role
class AdoptedChild(Role):
    name = "adopted_child"
    display = "Adopted Child"
    faction = VILLAGERS
    tags = frozenset({"villager_role"})
    description = (
        "You have access to one extra family chat, without being publicly known as part of that family. That "
        "family is told who you are. You can join your second family at any time - **ask the GMs in your private "
        "channel** when you want to."
    )
