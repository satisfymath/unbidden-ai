"""A Flask application's endpoints are read from its code: blueprints and their prefixes (declared or given at
registration), decorated routes with their methods, Flask-RESTful resources one endpoint per method, each with the
handler's file and line. The shapes are ihatemoney's (spiral-project), the first Flask application Unbidden met."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from unbidden.contracts.world import WorldModel
from unbidden.observe.stack import detect_stack
from unbidden.world.flask_routes import flask_endpoints, openapi_path
from unbidden.world.static import discover_static

pytestmark = pytest.mark.unit

FILES = {
    "ihatemoney/web.py": (
        "from flask import Blueprint\n"
        'main = Blueprint("main", __name__)\n\n'
        '@main.route("/healthcheck", methods=["GET"])\n'
        "def health():\n    return 'OK'\n\n"
        '@main.route("/<project_id>/")\n'
        "def list_bills():\n    bills = g.project.get_bills()\n    return bills\n\n"
        '@main.route("/<project_id>/edit/<int:bill_id>", methods=["GET", "POST"])\n'
        "def edit_bill(bill_id):\n    return 'x'\n\n"
        '@main.get("/<project_id>/export/<string:file>.<string:format>")\n'
        "def export_project(file, format):\n    return 'x'\n"
    ),
    "ihatemoney/api/common.py": (
        "from flask_restful import Resource\n\n"
        "class BillsHandler(Resource):\n"
        "    method_decorators = [need_auth]\n\n"
        "    def get(self, project):\n        return project.get_bills()\n\n"
        "    def post(self, project):\n        return 'x'\n\n"
        "class BillHandler(Resource):\n"
        "    def get(self, project, bill_id):\n        return 'x'\n\n"
        "    def delete(self, project, bill_id):\n        return 'x'\n"
    ),
    "ihatemoney/api/v1/resources.py": (
        "from flask import Blueprint\nfrom flask_restful import Api\n"
        "from ihatemoney.api.common import BillHandler, BillsHandler\n\n"
        'api = Blueprint("api", __name__, url_prefix="/api")\n'
        "restful_api = Api(api)\n"
        'restful_api.add_resource(BillsHandler, "/projects/<string:project_id>/bills")\n'
        "restful_api.add_resource(\n"
        '    BillHandler, "/projects/<string:project_id>/bills/<int:bill_id>"\n'
        ")\n"
    ),
    "ihatemoney/api/v1/__init__.py": "from .resources import api\n",
    "ihatemoney/run.py": (
        "from flask import Flask\nfrom ihatemoney.api.v1 import api as apiv1\n"
        "from ihatemoney.web import main as web_interface\n\n"
        "def create_app():\n    app = Flask(__name__)\n    app.register_blueprint(web_interface)\n"
        "    app.register_blueprint(apiv1)\n    return app\n"
    ),
    "requirements.txt": "flask\n",
}


def test_a_flask_rule_reads_as_an_openapi_path() -> None:
    assert openapi_path("/<project_id>/edit/<int:bill_id>") == "/{project_id}/edit/{bill_id}"
    assert openapi_path("/<project_id>/export/<string:file>.<string:format>") == "/{project_id}/export/{file}.{format}"
    assert openapi_path("/plain") == "/plain"


def test_blueprint_routes_and_restful_resources_become_endpoints_with_their_handlers() -> None:
    found = {(e.method, e.path): e for e in flask_endpoints(FILES)}
    assert set(found) == {
        ("GET", "/healthcheck"),
        ("GET", "/{project_id}/"),
        ("GET", "/{project_id}/edit/{bill_id}"),
        ("POST", "/{project_id}/edit/{bill_id}"),
        ("GET", "/{project_id}/export/{file}.{format}"),
        ("GET", "/api/projects/{project_id}/bills"),
        ("POST", "/api/projects/{project_id}/bills"),
        ("GET", "/api/projects/{project_id}/bills/{bill_id}"),
        ("DELETE", "/api/projects/{project_id}/bills/{bill_id}"),
    }
    bills = found[("GET", "/{project_id}/")]
    assert (bills.file, bills.line) == ("ihatemoney/web.py", 9), "the decorated function, not the decorator"
    api_get = found[("GET", "/api/projects/{project_id}/bills")]
    assert (api_get.file, api_get.line) == ("ihatemoney/api/common.py", 6), "the resource class's own method"
    api_post = found[("POST", "/api/projects/{project_id}/bills")]
    assert api_post.line == 9


def test_a_prefix_given_at_registration_counts_and_an_api_prefix_adds_to_it() -> None:
    files = {
        "app/views.py": (
            "from flask import Blueprint\n"
            'bp = Blueprint("views", __name__)\n'
            '@bp.route("/items", methods=["GET", "POST"])\ndef items(): ...\n'
        ),
        "app/api.py": (
            "from flask import Blueprint\nfrom flask_restful import Api\n"
            'api_bp = Blueprint("api", __name__)\n'
            'rest = Api(api_bp, prefix="/v2")\n'
            "class Things(Resource):\n    def get(self): ...\n"
            'rest.add_resource(Things, "/things", "/things/<int:id>")\n'
        ),
        "app/__init__.py": (
            "from flask import Flask\nfrom app.views import bp\nfrom app.api import api_bp\n"
            'app = Flask(__name__)\napp.register_blueprint(bp, url_prefix="/admin")\n'
            'app.register_blueprint(api_bp, url_prefix="/api")\n'
        ),
    }
    names = {f"{e.method} {e.path}" for e in flask_endpoints(files)}
    assert names == {"GET /admin/items", "POST /admin/items", "GET /api/v2/things", "GET /api/v2/things/{id}"}


def test_no_flask_in_the_sources_reads_nothing() -> None:
    assert (
        flask_endpoints({"app/main.py": 'from fastapi import FastAPI\napp = FastAPI()\n@app.get("/x")\ndef x(): ...\n'})
        == []
    )


def test_static_discovery_adds_flask_endpoints_and_does_not_read_them_as_fastapi(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    for path, text in FILES.items():
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_text(text)
    git = ["git", "-C", str(tmp_path), "-c", "user.name=t", "-c", "user.email=t@t"]
    subprocess.run([*git, "add", "."], check=True)
    subprocess.run([*git, "commit", "-qm", "x"], check=True)
    world = WorldModel(rev="HEAD")
    discover_static(tmp_path, "HEAD", detect_stack(tmp_path), world)
    endpoints = {e.name: e for e in world.of_kind("endpoint")}
    assert "GET /api/projects/{project_id}/bills" in endpoints and "GET /{project_id}/" in endpoints
    assert "GET /{project_id}/export/{file}.{format}" in endpoints, "`@main.get` is Flask's, with the prefix"
    assert all(
        e.attributes.get("framework") == "flask" and e.attributes.get("prefix_known") for e in endpoints.values()
    )
    assert len(endpoints) == 9
