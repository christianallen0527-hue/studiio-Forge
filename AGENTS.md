# Studio Forge / AUTOEDITING FORGE

Editorial-only automated editing pipeline + Studio Forge desktop UI.

## Cursor Cloud specific instructions

- Repo: `christianallen0527-hue/studiio-Forge`
- Python 3.12 venv at `.venv` — create with `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`
- UI server: `STUDIO_FORGE=1 .venv/bin/python -u ui/server.py` (port 8765)
- Desktop launcher lives in `desktop_app/Studio Forge.app` and `ui/Open Studio Forge.command`
- Do not commit `.env` — use Cursor Secrets / `.env.example` for API keys
- Product constraint: editorial only (no grade / reframe / face-track); 180° rotate is OK
- Learning store: `data/learning/store.json`; Obsidian notes under `context_docs/obsidian/`
- Prefer NAS Inbox/Jobs for permanent media; Mac SSD is staging
