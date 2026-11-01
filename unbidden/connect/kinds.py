"""The connectors Unbidden ships, by the kind a grant names."""

from __future__ import annotations

from unbidden.connect.base import Connector


def connectors() -> dict[str, Connector]:
    from unbidden.connect.github import GitHubConnector
    from unbidden.connect.http_api import HttpApiConnector
    from unbidden.connect.postgres import PostgresConnector

    return {"github": GitHubConnector(), "http_api": HttpApiConnector(), "postgres": PostgresConnector()}
