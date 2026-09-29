"""`taller cockpit`: serve Taller's own pages on this machine (spec 12, 3.1).

A web server, never the chief: a ticket's work is `taller ticket run` in its own
process, which this only starts and watches. Bound to 127.0.0.1 because there is
no authentication and one operator (spec 1.1).
"""

from __future__ import annotations

import socket
import webbrowser
from typing import Any

from ..errors import ConfigError
from ..prompter import Prompter

HOST = "127.0.0.1"
DEFAULT_PORT = 8765


def run(args: Any, prompter: Prompter) -> int:
    port = int(getattr(args, "port", None) or DEFAULT_PORT)
    if _in_use(port):
        raise ConfigError(
            f"Port {port} is already in use on this machine, and Taller will not take it "
            f"from whatever is there. Close that, or choose another: "
            f"`taller cockpit --port {port + 1}`.")

    from cockpit import create_app

    url = f"http://{HOST}:{port}/"
    prompter.say(f"The cockpit is at {url} - this machine only. Ctrl-C stops it.")
    if not getattr(args, "no_open", False):
        _open_in_browser(url)
    _serve(create_app(), HOST, port)
    return 0


def _in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        return probe.connect_ex((HOST, port)) == 0


def _serve(app: Any, host: str, port: int) -> None:
    """The one place the server is started, so a test can stand in for it."""
    app.run(host=host, port=port, threaded=True)


def _open_in_browser(url: str) -> None:
    webbrowser.open(url)
