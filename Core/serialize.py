"""Generic dataclass <-> JSON-friendly dict conversion.

Everything stored in the database goes through `dump`/`load`, so game
state, previews and snapshots all share one code path. Classes deriving
from `Polymorphic` are written with a `__type__` tag so a field typed as a
base class (e.g. `Role`) comes back as the right subclass.

Schema evolution is forgiving on purpose: missing fields fall back to their
defaults and unknown keys are ignored, so adding a field to a role never
breaks a stored game.
"""
from __future__ import annotations

import dataclasses
import enum
import sys
import types
import typing
from typing import Any, ClassVar, Union, get_args, get_origin

TYPE_KEY = "__type__"

_POLY_REGISTRY: dict[str, dict[str, type]] = {}
_HINTS_CACHE: dict[type, dict[str, Any]] = {}
_EXTRA_NS: dict[str, Any] = {}


def register_type_names(**names: Any) -> None:
    """Make names resolvable in string annotations of any module (used for
    forward references that are only imported under TYPE_CHECKING)."""
    _EXTRA_NS.update(names)
    _HINTS_CACHE.clear()


class Polymorphic:
    """Mixin for dataclass families stored with a type tag.

    A direct subclass names its family: `class Effect(Polymorphic, family="effect")`.
    Every subclass is registered under `_poly_tag()` - the class name unless
    overridden."""

    __poly_family__: ClassVar[str]

    def __init_subclass__(cls, family: str | None = None, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if family is not None:
            cls.__poly_family__ = family
        if not hasattr(cls, "__poly_family__"):
            raise TypeError(f"{cls.__name__} must declare a polymorphic family")
        tag = cls._poly_tag()
        registry = _POLY_REGISTRY.setdefault(cls.__poly_family__, {})
        existing = registry.get(tag)
        if existing is not None and existing.__qualname__ != cls.__qualname__:
            raise TypeError(f"Duplicate {cls.__poly_family__} type tag '{tag}' ({existing} vs {cls})")
        registry[tag] = cls

    @classmethod
    def _poly_tag(cls) -> str:
        return cls.__name__


def poly_lookup(family: str, tag: str) -> type | None:
    return _POLY_REGISTRY.get(family, {}).get(tag)


def transient(**kwargs: Any) -> Any:
    """A dataclass field that is never written to the database."""
    metadata = dict(kwargs.pop("metadata", {}) or {})
    metadata["transient"] = True
    return dataclasses.field(metadata=metadata, **kwargs)


# --- dump ------------------------------------------------------------------

def dump(obj: Any) -> Any:
    if obj is None or isinstance(obj, (bool, int, float, str)):
        if isinstance(obj, enum.Enum):  # str/int-mixin enums
            return obj.value
        return obj
    if isinstance(obj, enum.Enum):
        return obj.value
    if hasattr(obj, "__raw_dump__"):
        return obj.__raw_dump__()
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        out: dict[str, Any] = {}
        if isinstance(obj, Polymorphic):
            out[TYPE_KEY] = type(obj)._poly_tag()
        for f in dataclasses.fields(obj):
            if f.metadata.get("transient"):
                continue
            out[f.name] = dump(getattr(obj, f.name))
        return out
    if isinstance(obj, dict):
        return {_dump_key(k): dump(v) for k, v in obj.items()}
    if isinstance(obj, (set, frozenset)):
        items = [dump(v) for v in obj]
        try:
            return sorted(items)
        except TypeError:
            return items
    if isinstance(obj, (list, tuple)):
        return [dump(v) for v in obj]
    raise TypeError(f"Cannot serialise {type(obj).__name__}: {obj!r}")


def _dump_key(key: Any) -> str:
    if isinstance(key, enum.Enum):
        return str(key.value)
    if isinstance(key, (str, int)):
        return str(key)
    raise TypeError(f"Unsupported dict key type {type(key).__name__}")


# --- load ------------------------------------------------------------------

def load(tp: Any, data: Any) -> Any:
    if tp is Any or tp is object:
        return data

    origin = get_origin(tp)

    if origin is Union or origin is types.UnionType:
        args = [a for a in get_args(tp) if a is not type(None)]
        if data is None:
            return None
        if len(args) == 1:
            return load(args[0], data)
        for arg in args:  # pick the primitive that matches, else the first
            if isinstance(arg, type) and not dataclasses.is_dataclass(arg) and isinstance(data, arg):
                return data
        return load(args[0], data)

    if origin is typing.Literal:
        return data

    if origin is ClassVar:
        return data

    if origin in (list, typing.List):
        (item_tp,) = get_args(tp) or (Any,)
        return [load(item_tp, v) for v in data]
    if origin in (set, frozenset):
        (item_tp,) = get_args(tp) or (Any,)
        return origin(load(item_tp, v) for v in data)
    if origin is tuple:
        args = get_args(tp)
        if len(args) == 2 and args[1] is Ellipsis:
            return tuple(load(args[0], v) for v in data)
        return tuple(load(a, v) for a, v in zip(args, data))
    if origin in (dict, typing.Dict):
        key_tp, val_tp = get_args(tp) or (Any, Any)
        return {_load_key(key_tp, k): load(val_tp, v) for k, v in data.items()}

    if isinstance(tp, type):
        if data is None:
            return None
        if issubclass(tp, enum.Enum):
            return tp(data)
        if tp is bool:
            return bool(data)
        if tp is int:
            return int(data)
        if tp is float:
            return float(data)
        if tp is str:
            return str(data)
        if dataclasses.is_dataclass(tp):
            return _load_dataclass(tp, data)
        if tp in (list, dict, set, tuple):
            return tp(data)
    return data


def _load_key(key_tp: Any, key: str) -> Any:
    if key_tp is int:
        return int(key)
    if isinstance(key_tp, type) and issubclass(key_tp, enum.Enum):
        return key_tp(key)
    return key


def _load_dataclass(tp: type, data: dict[str, Any]) -> Any:
    cls = tp
    if issubclass(tp, Polymorphic) and isinstance(data, dict) and TYPE_KEY in data:
        found = poly_lookup(tp.__poly_family__, data[TYPE_KEY])
        if found is None:
            fallback = getattr(tp, "__missing_type__", None)
            if fallback is None:
                raise TypeError(f"Unknown {tp.__poly_family__} type '{data[TYPE_KEY]}'")
            return fallback(data)
        cls = found

    hints = _type_hints(cls)
    init_kwargs: dict[str, Any] = {}
    late: dict[str, Any] = {}
    for f in dataclasses.fields(cls):
        if f.metadata.get("transient") or f.name not in data:
            continue
        value = load(hints.get(f.name, Any), data[f.name])
        if f.init:
            init_kwargs[f.name] = value
        else:
            late[f.name] = value
    obj = cls(**init_kwargs)
    for name, value in late.items():
        setattr(obj, name, value)
    return obj


def _type_hints(cls: type) -> dict[str, Any]:
    hints = _HINTS_CACHE.get(cls)
    if hints is None:
        hints = {}
        for base in reversed(cls.__mro__):
            if not dataclasses.is_dataclass(base):
                continue
            module_ns = dict(vars(sys.modules[base.__module__]))
            for name, ann in base.__dict__.get("__annotations__", {}).items():
                if isinstance(ann, str):
                    try:
                        ann = eval(ann, module_ns, _EXTRA_NS)  # noqa: S307 - our own annotations
                    except NameError:
                        ann = Any
                hints[name] = ann
        _HINTS_CACHE[cls] = hints
    return hints
