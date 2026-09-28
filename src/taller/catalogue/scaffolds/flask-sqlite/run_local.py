"""Run on this machine: python run_local.py (PORT picks another port)."""

import os

from app import create_app

if __name__ == "__main__":
    create_app().run(host="127.0.0.1", port=int(os.environ.get("PORT", "5000")), debug=True)
