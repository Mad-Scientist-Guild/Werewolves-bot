import importlib
import pkgutil

# Importing each submodule is enough to make its @register_role calls run
# nothing needs to be re-exported from here
# Callers do `from roles.role import ROLE_REGISTRY` (or wherever ROLE_REGISTRY ends up) after this package has been imported once
for _, module_name, _ in pkgutil.iter_modules(__path__):
    importlib.import_module(f"{__name__}.{module_name}")