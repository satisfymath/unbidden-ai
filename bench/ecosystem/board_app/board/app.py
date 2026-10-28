"""The Depot picker's restock board: GET /board."""

from __future__ import annotations

import html
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from board import sources
from board.shortage import rows

HERE = Path(__file__).parent


def render(table: list) -> str:
    body = "\n".join(
        f'<tr class="row" data-bin="{html.escape(r.bin)}"><td class="bin">{html.escape(r.bin)}</td>'
        f'<td class="zone">Zone {r.zone}</td><td class="num">{r.supply}</td><td class="num">{r.picks}</td>'
        f'<td class="state">{badge(r)}</td></tr>'
        for r in table
    )
    short = sum(1 for r in table if r.short)
    page = (HERE / "templates" / "board.html").read_text()
    return page.replace("{{rows}}", body).replace("{{short}}", str(short)).replace("{{total}}", str(len(table)))


def badge(r) -> str:
    if r.short:
        return f'<span class="badge short">SHORT {r.shortfall}</span>'
    return '<span class="badge ok">OK</span>'


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/board.css":
            data, kind = (HERE / "static" / "board.css").read_bytes(), "text/css"
        elif self.path in ("/", "/board"):
            data, kind = render(rows(sources.bins(), sources.picks_7d())).encode(), "text/html; charset=utf-8"
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8000), Handler).serve_forever()
