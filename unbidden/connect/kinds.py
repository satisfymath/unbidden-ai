"""The connectors a grant may name by kind: the ones Unbidden ships, and the ones installed packages add
(`unbidden.plugins`, group `unbidden.connectors`). A plugin never replaces a shipped kind."""

from __future__ import annotations

from unbidden.connect.base import Connector


def connectors() -> dict[str, Connector]:
    from unbidden.connect.github import GitHubConnector
    from unbidden.connect.http_api import HttpApiConnector
    from unbidden.connect.postgres import PostgresConnector
    from unbidden.plugins import connectors as plugged

    shipped: dict[str, Connector] = {
        "github": GitHubConnector(),
        "http_api": HttpApiConnector(),
        "postgres": PostgresConnector(),
    }
    return {**plugged(), **shipped}
