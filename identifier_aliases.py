"""The single MCP-facing vocabulary for Vetmanager reference identifiers."""

from __future__ import annotations

import inspect
import re
from functools import wraps
from filters import OptionalJsonList

from fastmcp.exceptions import ToolError
from fastmcp.server.middleware import Middleware
from filters import FILTER_FIELDS_BY_ENTITY
from list_projection import (
    LIST_FIELDS, PET_CONTACT_TOOLS, mask_pet_list_result,
    project_list_result, selected_fields, selected_include,
)
from tool_descriptions import RAW_CLAUSE_ENTITIES


ALIAS_TO_CANONICAL = {
    "patient_id": "pet_id",
    "owner_id": "client_id",
    "user_id": "doctor_id",
}
_OLD_NAMES = re.compile(r"\b(?:" + "|".join(map(re.escape, ALIAS_TO_CANONICAL)) + r")\b")


def public_text(value: str) -> str:
    return _OLD_NAMES.sub(lambda match: ALIAS_TO_CANONICAL[match.group()], value)


def canonical_name(name: str) -> str:
    return ALIAS_TO_CANONICAL.get(name, name)


def normalize_arguments(arguments: dict, *, tool_name: str) -> dict:
    """Accept old names but send only canonical names to FastMCP validation."""
    result = dict(arguments)
    for alias, canonical in ALIAS_TO_CANONICAL.items():
        if alias not in result:
            continue
        value = result.pop(alias)
        if canonical in result and result[canonical] != value:
            raise ToolError(f"Conflicting values for {canonical}.")
        result[canonical] = value
    entity = RAW_CLAUSE_ENTITIES.get(tool_name)
    allowed = FILTER_FIELDS_BY_ENTITY.get(entity, frozenset())
    for clause in ("filter", "sort"):
        items = result.get(clause)
        if not isinstance(items, list):
            continue
        converted = []
        seen_names: dict[str, dict[str, tuple[dict, bool]]] = {}
        for item in items:
            if not isinstance(item, dict) or not isinstance(item.get("property"), str):
                converted.append(item)
                continue
            property_name = item["property"]
            canonical = canonical_name(property_name)
            shape = {key: value for key, value in item.items() if key != "property"}
            spellings = seen_names.setdefault(canonical, {})
            if any(name != property_name and (varied or previous != shape)
                   for name, (previous, varied) in spellings.items()):
                raise ToolError(f"Conflicting {clause} clauses for {canonical}.")
            first, varied = spellings.get(property_name, (shape, False))
            spellings[property_name] = (first, varied or first != shape)
            api_name = canonical if canonical in allowed else next(
                (old for old, new in ALIAS_TO_CANONICAL.items()
                 if new == canonical and old in allowed), canonical
            )
            converted.append({**item, "property": api_name})
        result[clause] = converted
    return result


def normalize_result(value, *, report_mode: bool = False, report_rows: bool = False):
    """Rename identifier keys at every structured response depth."""
    if isinstance(value, list):
        return [normalize_result(item, report_mode=report_mode, report_rows=report_rows) for item in value]
    if isinstance(value, tuple):
        return tuple(normalize_result(item, report_mode=report_mode, report_rows=report_rows) for item in value)
    if not isinstance(value, dict):
        return value
    if report_rows:
        return value
    result = {}
    conflicts = []
    # An explicit canonical key wins independent of the VM object's key order.
    for key, item in value.items():
        if isinstance(key, str) and canonical_name(key) == key:
            result[key] = normalize_result(item, report_mode=report_mode,
                                           report_rows=key in {"rows", "columns", "preview_example_row"} and report_mode)
    for key, item in value.items():
        public_key = canonical_name(key) if isinstance(key, str) else key
        if public_key == key:
            continue
        normalized = normalize_result(item, report_mode=report_mode)
        if public_key in result and result[public_key] != normalized:
            conflicts.append({"field": public_key, "values": [result[public_key], normalized]})
        else:
            result[public_key] = normalized
    if conflicts:
        result["_mcp_identifier_conflicts"] = conflicts
    return result


def canonical_tool(func, *, tool_name: str, report_mode: bool = False):
    """Publish a canonical signature while calling the existing VM adapter."""
    original = inspect.signature(func)
    original_names = tuple(original.parameters)
    renamed = [parameter.replace(name=canonical_name(parameter.name))
               for parameter in original.parameters.values()]
    if tool_name in LIST_FIELDS:
        renamed.extend((
            inspect.Parameter("fields", inspect.Parameter.KEYWORD_ONLY,
                              default=None, annotation=OptionalJsonList[str]),
            inspect.Parameter("compact", inspect.Parameter.KEYWORD_ONLY,
                              default=False, annotation=bool),
            inspect.Parameter("include", inspect.Parameter.KEYWORD_ONLY,
                              default=None, annotation=OptionalJsonList[str]),
            inspect.Parameter("mask_contacts", inspect.Parameter.KEYWORD_ONLY,
                              default=False, annotation=bool),
        ))
    elif tool_name in PET_CONTACT_TOOLS:
        renamed.append(inspect.Parameter(
            "mask_contacts", inspect.Parameter.KEYWORD_ONLY,
            default=False, annotation=bool,
        ))
    public_signature = original.replace(parameters=renamed)

    @wraps(func)
    async def _canonical(*args, **kwargs):
        projection_options = None
        if tool_name in LIST_FIELDS:
            projection_options = (
                kwargs.pop("fields", None), kwargs.pop("compact", False),
                kwargs.pop("include", None), kwargs.pop("mask_contacts", False),
            )
        pet_mask_contacts = kwargs.pop("mask_contacts", False) if tool_name in PET_CONTACT_TOOLS else False
        original_kwargs = {}
        for old in original_names:
            public = canonical_name(old)
            if public in kwargs:
                original_kwargs[old] = kwargs.pop(public)
            elif old in kwargs:
                original_kwargs[old] = kwargs.pop(old)
        original_kwargs.update(kwargs)
        if projection_options is not None:
            original_kwargs["_mcp_projection_options"] = projection_options
        try:
            result = await func(*args, **original_kwargs)
            normalized = normalize_result(result, report_mode=report_mode)
            if projection_options is not None:
                return project_list_result(
                    normalized, tool_name,
                    selected_fields(tool_name, *projection_options[:2]),
                    include=selected_include(tool_name, projection_options[2]),
                    mask_contacts=projection_options[3],
                )
            if pet_mask_contacts:
                return mask_pet_list_result(normalized, tool_name)
            return normalized
        except Exception as exc:
            if isinstance(exc, ToolError) or exc.__class__.__name__ in {
                "FilterPropertyValidationError", "SortPropertyValidationError"
            }:
                exc.args = (public_text(str(exc)),)
            raise

    _canonical.__signature__ = public_signature
    _canonical.__annotations__ = {
        canonical_name(name) if name != "return" else name: annotation
        for name, annotation in getattr(func, "__annotations__", {}).items()
    }
    if tool_name in LIST_FIELDS:
        _canonical.__annotations__.update({
            "fields": OptionalJsonList[str], "compact": bool,
            "include": OptionalJsonList[str], "mask_contacts": bool,
        })
    elif tool_name in PET_CONTACT_TOOLS:
        _canonical.__annotations__["mask_contacts"] = bool
    _canonical.__doc__ = public_text(func.__doc__ or "")
    return _canonical


class IdentifierAliasMiddleware(Middleware):
    async def on_call_tool(self, context, call_next):
        context.message.arguments = normalize_arguments(
            context.message.arguments or {}, tool_name=context.message.name
        )
        return await call_next(context)
