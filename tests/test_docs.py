from Core.actor import MODIFIER_REGISTRY, ROLE_REGISTRY
from Services.role_commands import COMMAND_GROUPS
from tools.generate_docs import build


def test_player_guide_covers_every_role_and_modifier():
    text = build()
    for cls in [*ROLE_REGISTRY.values(), *MODIFIER_REGISTRY.values()]:
        assert f"### {cls.title()}" in text, cls.name


def test_every_ability_has_a_command_group():
    """A role with abilities must have a command cog, or players can't use them."""
    for cls in [*ROLE_REGISTRY.values(), *MODIFIER_REGISTRY.values()]:
        if cls.abilities:
            assert cls.name in COMMAND_GROUPS, f"{cls.name} has abilities but no RoleCommands group"
