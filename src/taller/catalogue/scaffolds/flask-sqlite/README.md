# %%name%%

%%description%%

## Run it here

```bash
python -m venv venv
venv/bin/pip install -r requirements-dev.txt    # venv\Scripts\pip on Windows
python run_local.py
```

Then open http://127.0.0.1:5000/.

## Test

```bash
python -m pytest -q
```

Built with Taller: start from `.taller/constitution/00-index.md`.
