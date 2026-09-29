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

    app = application()
    url = f"http://{HOST}:{port}/"
    prompter.say(f"The cockpit is at {url} - this machine only. Ctrl-C stops it.")
    if not getattr(args, "no_open", False):
        _open_in_browser(url)
    _serve(app, HOST, port)
    return 0


def application() -> Any:
    """The cockpit's Flask application.

    `cockpit/` is a second top-level package, so an installation made before it
    existed does not carry it - and an import error is not a sentence she can act
    on. Reinstalling Taller is what fixes it.
    """
    try:
        from cockpit import create_app
    except ImportError as exc:
        raise ConfigError(
            "Taller's own pages are not in this installation, so the cockpit cannot "
            "start. Reinstall Taller from its folder - `pip install -e .` in the taller "
            f"repository, or `pip install --upgrade taller` - and try again. ({exc})"
        ) from exc
    return create_app()


def _in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        return probe.connect_ex((HOST, port)) == 0


def _serve(app: Any, host: str, port: int) -> None:
    """The one place the server is started, so a test can stand in for it."""
    app.run(host=host, port=port, threaded=True)


def _open_in_browser(url: str) -> None:
    webbrowser.open(url)
