"""Endpoints a Flask application declares, read from the code without running it.

FastAPI and anything with an OpenAPI document are read elsewhere (`static.py`, `runtime.py`); a Flask application
serves no document, so its routes are only here: `@bp.route(path, methods=[...])` and `@bp.get/post/...` on a
`Blueprint` or the app, with the blueprint's `url_prefix` (declared on the blueprint, or given to
`register_blueprint`); Flask-RESTful's `api.add_resource(Cls, "/path", ...)`, one endpoint per HTTP method the
resource class defines, under the `Api`'s own `prefix` and the blueprint it is bound to. A route's `<int:x>` is
`{x}`, as OpenAPI writes it, so the live document (when there is one) reconciles the same way.

Each endpoint carries the file and line of its handler: `column_use` reads that handler's calls to say which
endpoints look rows up by a column, and the labs read it to know what the request reaches."""

from __future__ import annotations

import re
from dataclasses import dataclass

_BLUEPRINT = re.compile(r"^(?P<obj>\w+)\s*=\s*Blueprint\(\s*[\"'](?P<name>\w+)[\"'](?P<args>[^)]*)\)", re.M)
_URL_PREFIX = re.compile(r"url_prefix\s*=\s*[\"'](?P<prefix>[^\"']*)[\"']")
_REGISTER = re.compile(r"\.register_blueprint\(\s*(?P<target>[\w.]+)(?P<args>[^)]*)\)")
_ROUTE = re.compile(
    r"^\s*@(?P<obj>\w+)\.(?P<kind>route|get|post|put|patch|delete)\(\s*[\"'](?P<path>[^\"']*)[\"'](?P<args>[^)]*)\)",
    re.M,
)
_METHODS = re.compile(r"methods\s*=\s*[\[(]([^\])]*)[\])]")
_API = re.compile(r"^(?P<obj>\w+)\s*=\s*Api\(\s*(?P<target>\w+)?(?P<args>[^)]*)\)", re.M)
_API_PREFIX = re.compile(r"prefix\s*=\s*[\"'](?P<prefix>[^\"']*)[\"']")
_ADD_RESOURCE = re.compile(r"(?P<obj>\w+)\.add_resource\(\s*(?P<cls>\w+)\s*,(?P<rest>[^)]*)\)", re.S)
_PATHS = re.compile(r"[\"']([^\"']*)[\"']")
_CLASS = re.compile(r"^class\s+(?P<name>\w+)\s*\(", re.M)
_HANDLER_METHOD = re.compile(r"^(?P<indent>[ \t]+)def\s+(?P<name>get|post|put|patch|delete)\s*\(", re.M)
_CONVERTER = re.compile(r"<(?:\w+(?:\([^)]*\))?:)?(?P<name>\w+)>")
_DEF = re.compile(r"^\s*(?:async\s+)?def\s+\w+\s*\(", re.M)
_IMPORT_FROM = re.compile(r"^from\s+(?P<mod>[\w.]+)\s+import\s+(?:\((?P<group>[^)]*)\)|(?P<line>[^\n]+))", re.M)


@dataclass(frozen=True)
class FlaskEndpoint:
    method: str
    path: str  # OpenAPI shape: `/projects/{project_id}/bills`
    file: str
    line: int  # the handler's line (the decorated function, or the resource class's method)


def openapi_path(rule: str) -> str:
    """Flask's `<int:bill_id>` and `<project_id>` as OpenAPI's `{bill_id}`; a trailing `.<string:format>` keeps
    its dot."""
    return _CONVERTER.sub(lambda m: "{" + m.group("name") + "}", rule)


def _join(prefix: str, path: str) -> str:
    if not prefix:
        return path or "/"
    if not path or path == "/":
        return prefix
    return prefix.rstrip("/") + "/" + path.lstrip("/")


def _next_def_line(text: str, start: int) -> int:
    """The line of the first `def` at or after `start`: the function a decorator decorates."""
    match = _DEF.search(text, start)
    return text[: match.start() if match else start].count("\n") + 1


def _blueprint_prefixes(sources: dict[str, str]) -> dict[tuple[str, str], str]:
    """`(file, blueprint variable) -> url_prefix`: declared on the Blueprint, else given when it is registered
    (`app.register_blueprint(apiv1, url_prefix="/api")`), followed through `from x import y as z`."""
    declared: dict[tuple[str, str], str] = {}
    names: dict[tuple[str, str], tuple[str, str]] = {}  # (file, var) -> (file, var) where the blueprint lives
    for path, text in sources.items():
        for m in _BLUEPRINT.finditer(text):
            prefix = _URL_PREFIX.search(m.group("args"))
            declared[(path, m.group("obj"))] = prefix.group("prefix") if prefix else ""
    files = set(sources)
    for path, text in sources.items():
        for m in _IMPORT_FROM.finditer(text):
            module = m.group("mod").replace(".", "/")
            owner = next((f for f in files if f in (f"{module}.py", f"{module}/__init__.py")), None)
            if owner is None:
                continue
            for name in (m.group("group") or m.group("line") or "").split("#")[0].split(","):
                original, _, alias = name.strip().partition(" as ")
                if original.isidentifier():
                    names[(path, (alias.strip() or original))] = (owner, original)
    # A package `__init__` that re-exports (`from .resources import api`) points one level further.
    for key, (owner, original) in list(names.items()):
        seen = {key}
        while (owner, original) in names and (owner, original) not in seen:
            seen.add((owner, original))
            owner, original = names[(owner, original)]
        names[key] = (owner, original)
    for path, text in sources.items():
        for m in _REGISTER.finditer(text):
            given = _URL_PREFIX.search(m.group("args"))
            if given is None:
                continue
            head = m.group("target").split(".")[0]
            target = names.get((path, head), (path, head))
            if target in declared and not declared[target]:
                declared[target] = given.group("prefix")
    return declared


def flask_endpoints(sources: dict[str, str]) -> list[FlaskEndpoint]:
    """Every route the sources declare, with its handler's file and line."""
    if not any("Blueprint(" in t or "Flask(" in t or "add_resource(" in t for t in sources.values()):
        return []
    prefixes = _blueprint_prefixes(sources)
    found: list[FlaskEndpoint] = []
    # Decorated routes.
    for path, text in sources.items():
        for m in _ROUTE.finditer(text):
            obj = m.group("obj")
            prefix = prefixes.get((path, obj), "")
            methods = ["GET"]
            if m.group("kind") == "route":
                given = _METHODS.search(m.group("args"))
                if given:
                    methods = [x.strip().strip("\"'").upper() for x in given.group(1).split(",") if x.strip()]
            else:
                methods = [m.group("kind").upper()]
            line = _next_def_line(text, m.end())
            for method in methods:
                found.append(FlaskEndpoint(method, openapi_path(_join(prefix, m.group("path"))), path, line))
    # Flask-RESTful resources.
    classes: dict[str, tuple[str, dict[str, int]]] = {}  # class -> (file, {method: line})
    for path, text in sources.items():
        for cm in _CLASS.finditer(text):
            body_end = text.find("\nclass ", cm.end())
            body = text[cm.end() : body_end if body_end != -1 else len(text)]
            methods = {
                hm.group("name").upper(): text[: cm.end() + hm.start()].count("\n") + 1
                for hm in _HANDLER_METHOD.finditer(body)
            }
            if methods:
                classes[cm.group("name")] = (path, methods)
    for path, text in sources.items():
        apis: dict[str, str] = {}
        for am in _API.finditer(text):
            bound = am.group("target") or ""
            prefix = prefixes.get((path, bound), "")
            own = _API_PREFIX.search(am.group("args"))
            apis[am.group("obj")] = _join(prefix, own.group("prefix")) if own else prefix
        for rm in _ADD_RESOURCE.finditer(text):
            if rm.group("obj") not in apis or rm.group("cls") not in classes:
                continue
            file, methods = classes[rm.group("cls")]
            for rule in _PATHS.findall(rm.group("rest")):
                route = openapi_path(_join(apis[rm.group("obj")], rule))
                for method, line in sorted(methods.items()):
                    found.append(FlaskEndpoint(method, route, file, line))
    unique: dict[tuple[str, str], FlaskEndpoint] = {}
    for endpoint in found:
        unique.setdefault((endpoint.method, endpoint.path), endpoint)
    return list(unique.values())
