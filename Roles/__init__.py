"""Role plug-ins.

Every module below this package (recursively) is imported once, which runs
its @register_role / @register_modifier decorators and defines its command
cog. Adding a role = adding a file; removing a role = deleting its file.
Modules whose name starts with an underscore are imported too (shared
helpers), but are not expected to define roles.
"""
import importlib
import pkgutil

for _module in pkgutil.walk_packages(__path__, prefix=f"{__name__}."):
    importlib.import_module(_module.name)
