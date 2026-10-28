"""Shopfront: the shop's storefront. Lists what can be ordered, from the warehouse's stock."""

import json
import os
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def stock() -> list[dict]:
    items, page, pages = [], 1, 1
    while page <= pages:
        request = urllib.request.Request(
            f"{os.environ['STOCKROOM_URL']}/v1/items?page={page}",
            headers={"X-Stockroom-Key": os.environ.get("STOCKROOM_KEY", "")},
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            body = json.load(response)
        items, pages, page = items + body["items"], body["pages"], page + 1
    return items


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/health":
            body, status = {"ok": True}, 200
        elif self.path == "/api/availability":
            try:
                body = [{"sku": i["sku"], "available": i["on_hand"] - i["reserved"] > 0} for i in stock()]
                status = 200
            except Exception as exc:
                body, status = {"error": str(exc)}, 502
        else:
            body, status = {"error": "not found"}, 404
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(data)


ThreadingHTTPServer(("0.0.0.0", 8000), Handler).serve_forever()
