"""OpenAPI schemas, read by the version the document declares, and validated as JSON Schema 2020-12.

OpenAPI 3.0 schemas are "an extended subset" of JSON Schema Wright draft 00, not JSON Schema itself (OAS 3.0.3,
Schema Object); 3.1 schemas are JSON Schema 2020-12 plus annotations (OAS 3.1.0). Validating a 3.0 schema with a
JSON Schema validator misreads it: `nullable: true` is ignored (a documented `null` is rejected), a boolean
`exclusiveMinimum` is not a number. So each schema is translated once, when the document is read, into what it means
in JSON Schema 2020-12, and one validator serves both versions:

- 3.0 `nullable: true` adds `"null"` to the type, only where `type` is in the same schema object (the spec's rule);
  other keywords keep their meaning, so an `enum` without `null` still refuses it (OAS 3.0.3: "other Schema Object
  constraints retain their defined behavior, and therefore may disallow the use of null");
- 3.0 boolean `exclusiveMinimum`/`exclusiveMaximum` become the numeric form;
- 3.0 `readOnly` properties are not required in a request, `writeOnly` ones not in a response (`required` "will take
  effect on the response only" / "on the request only");
- `$ref`: local references are inlined; in 3.0 a reference's siblings are ignored (as JSON Reference says), in 3.1
  they apply beside it (`allOf`).

Refused with a reason rather than guessed: Swagger 2.0 and versions other than 3.0.x and 3.1.x; 3.0 type arrays (not
allowed in 3.0); `nullable` in a 3.1 document (not a 3.1 keyword: 3.1 writes `type: [T, "null"]`); another
`$schema` dialect in 3.1; remote or recursive `$ref`s.
"""

from __future__ import annotations

import re
from typing import Any, Literal

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

Version = Literal["3.0", "3.1"]
Direction = Literal["request", "response"]
DIALECTS = {None, "https://spec.openapis.org/oas/3.1/dialect/base", "https://json-schema.org/draft/2020-12/schema"}
MAX_DEPTH = 64
SUBSCHEMA_LISTS = ("allOf", "oneOf", "anyOf", "prefixItems")
SUBSCHEMA_ONE = ("items", "not", "additionalProperties", "contains", "propertyNames", "if", "then", "else")
SUBSCHEMA_MAPS = ("properties", "patternProperties", "$defs", "dependentSchemas")


class UnsupportedSchema(ValueError):
    """A document or schema this reader does not interpret, with why."""


def version(document: dict[str, Any]) -> Version:
    if "swagger" in document:
        raise UnsupportedSchema(f"Swagger {document['swagger']} documents are not read; OpenAPI 3.0 and 3.1 are")
    declared = str(document.get("openapi", ""))
    if declared.startswith("3.0."):
        return "3.0"
    if declared.startswith("3.1."):
        dialect = document.get("jsonSchemaDialect")
        if dialect not in DIALECTS:
            raise UnsupportedSchema(f"jsonSchemaDialect {dialect!r}: only the OAS 3.1 base dialect is read")
        return "3.1"
    raise UnsupportedSchema(f"openapi {declared or '(missing)'}: only 3.0.x and 3.1.x are read")


def resolve(document: dict[str, Any], schema: Any, v: Version, depth: int = 0) -> Any:
    """Inline local `$ref`s so each schema stands alone."""
    if depth > MAX_DEPTH:
        raise UnsupportedSchema("a $ref refers to itself (recursive schemas are not read)")
    if isinstance(schema, list):
        return [resolve(document, item, v, depth + 1) for item in schema]
    if not isinstance(schema, dict):
        return schema
    if "$ref" in schema:
        ref = str(schema["$ref"])
        if not ref.startswith("#/"):
            raise UnsupportedSchema(f"$ref {ref!r}: only references inside the document are read")
        target: Any = document
        for part in ref[2:].split("/"):
            part = part.replace("~1", "/").replace("~0", "~")
            if not isinstance(target, dict) or part not in target:
                raise UnsupportedSchema(f"$ref {ref!r} points nowhere in the document")
            target = target[part]
        inlined = resolve(document, target, v, depth + 1)
        siblings = {k: val for k, val in schema.items() if k != "$ref"}
        if v == "3.0" or not siblings:
            return inlined  # 3.0: siblings of a $ref are ignored
        return {"allOf": [inlined, resolve(document, siblings, v, depth + 1)]}
    return {k: resolve(document, val, v, depth + 1) for k, val in schema.items()}


def to_json_schema(schema: Any, v: Version, direction: Direction) -> Any:
    """What a resolved OpenAPI schema means, as JSON Schema 2020-12."""
    if not isinstance(schema, dict):
        return schema
    out = dict(schema)
    if v == "3.1":
        if "nullable" in out:
            raise UnsupportedSchema("`nullable` is not an OpenAPI 3.1 keyword; 3.1 writes type: [T, 'null']")
        if out.get("$schema") not in DIALECTS:
            raise UnsupportedSchema(f"$schema {out['$schema']!r}: only the OAS 3.1 base dialect is read")
    else:
        kind = out.get("type")
        if isinstance(kind, list):
            raise UnsupportedSchema(f"type {kind}: OpenAPI 3.0 allows one type (and `nullable`), not a list")
        if out.pop("nullable", False) is True and isinstance(kind, str):
            out["type"] = [kind, "null"]
        for bound, limit in (("exclusiveMinimum", "minimum"), ("exclusiveMaximum", "maximum")):
            if isinstance(out.get(bound), bool):
                exclusive = out.pop(bound)  # draft-05: a flag on `minimum`; 2020-12: the bound itself
                if exclusive and limit in out:
                    out[bound] = out.pop(limit)
        hidden = "readOnly" if direction == "request" else "writeOnly"
        props = out.get("properties")
        if isinstance(props, dict) and isinstance(out.get("required"), list):
            out["required"] = [
                r for r in out["required"] if not (isinstance(props.get(r), dict) and props[r].get(hidden) is True)
            ]
    for key in SUBSCHEMA_LISTS:
        if isinstance(out.get(key), list):
            out[key] = [to_json_schema(s, v, direction) for s in out[key]]
    for key in SUBSCHEMA_ONE:
        if isinstance(out.get(key), dict):
            out[key] = to_json_schema(out[key], v, direction)
    for key in SUBSCHEMA_MAPS:
        if isinstance(out.get(key), dict):
            out[key] = {name: to_json_schema(s, v, direction) for name, s in out[key].items()}
    return out


def read(document: dict[str, Any], schema: Any, direction: Direction) -> Any:
    """A schema of the document, resolved and translated: what every parameter, body and response is checked with."""
    if schema is None:
        return None
    v = version(document)
    translated = to_json_schema(resolve(document, schema, v), v, direction)
    Draft202012Validator.check_schema(translated)  # a schema that is not one is the document's error, said here
    return translated


def validate(value: Any, schema: dict[str, Any]) -> None:
    """Raise `jsonschema.ValidationError` when the value does not satisfy the (translated) schema."""
    error = next(iter(sorted(Draft202012Validator(schema).iter_errors(value), key=lambda e: e.path)), None)
    if error is not None:
        raise error


__all__ = ["UnsupportedSchema", "ValidationError", "read", "resolve", "to_json_schema", "validate", "version"]


# Deviations between a document and an observed response (stage 8) ------------------------------------------------

# Fields whose deviation always blocks: they identify records, relate them, or say how many there are.
IDENTITY = re.compile(
    r"(^|_)(id|ids|key|slug|code|uuid)$|Id$|^(total|count|next|next_cursor|cursor|page|pages)$|count$", re.I
)


def deviations(value: Any, schema: dict[str, Any]) -> list[dict[str, str]]:
    """What in `value` the (translated) schema does not admit, one entry per field: its path, what was declared,
    what was observed (`null`, `absent`, or a type), and whether a degraded read may continue past it. Only an
    undeclared null or an absent value may; any other mismatch, or anything at the top level, may not."""
    out: list[dict[str, str]] = []
    for error in Draft202012Validator(schema).iter_errors(value):
        path = "/".join(str(p) for p in error.absolute_path)
        if error.validator == "required":
            missing = re.findall(r"'([^']+)' is a required property", error.message)
            for name in missing or ["?"]:
                field = f"{path}/{name}" if path else name
                out.append({"field": field, "declared": "required", "observed": "absent", "degradable": "yes"})
        elif error.validator == "type" and error.instance is None:
            out.append({"field": path, "declared": f"type {error.validator_value}", "observed": "null",
                        "degradable": "yes" if path else "no"})  # fmt: skip
        else:
            declared = f"{error.validator} {error.validator_value}"[:80]
            out.append({"field": path or "(the response)", "declared": declared,
                        "observed": type(error.instance).__name__, "degradable": "no"})  # fmt: skip
    return out


def leaf(field: str) -> str:
    """The field's own name in a path ("articles/3/author/image" -> "image"), indexes skipped."""
    parts = [p for p in field.split("/") if p and not p.isdigit()]
    return parts[-1] if parts else field
