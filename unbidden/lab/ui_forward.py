"""Runs inside a container, never on the host: the capture's only way out. It listens on one port and relays each
connection to the same port of the host, where the project publishes its page. Written by Unbidden.

Usage (in the container): python ui_forward.py <port>
"""

from __future__ import annotations

import contextlib
import socket
import sys
import threading


def pipe(src: socket.socket, dst: socket.socket) -> None:
    try:
        while data := src.recv(65536):
            dst.sendall(data)
    except OSError:
        pass
    finally:
        for s in (src, dst):
            with contextlib.suppress(OSError):
                s.shutdown(socket.SHUT_RDWR)


def main() -> None:
    port = int(sys.argv[1])
    server = socket.create_server(("0.0.0.0", port))
    while True:
        client, _ = server.accept()
        try:
            upstream = socket.create_connection(("host.docker.internal", port), timeout=10)
        except OSError:
            client.close()
            continue
        upstream.settimeout(None)
        for a, b in ((client, upstream), (upstream, client)):
            threading.Thread(target=pipe, args=(a, b), daemon=True).start()


if __name__ == "__main__":
    main()
