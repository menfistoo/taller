"""Application factory for %%name%%."""
# %%description%%

import os

from flask import Flask

import database
from routes import bp as main_bp


def create_app(overrides: dict | None = None) -> Flask:
    app = Flask(__name__, instance_relative_config=True)
    app.config.update(
        # Unset, sessions do not survive a restart - safe, never guessable.
        SECRET_KEY=os.environ.get("SECRET_KEY") or os.urandom(32),
        DATABASE=os.environ.get("DATABASE") or os.path.join(app.instance_path, "app.db"),
    )
    if overrides:
        app.config.update(overrides)

    os.makedirs(os.path.dirname(os.path.abspath(app.config["DATABASE"])), exist_ok=True)
    database.init_db(app.config["DATABASE"])
    app.register_blueprint(main_bp)
    return app
