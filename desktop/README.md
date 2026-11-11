# FunPay Assistant Desktop

Windows desktop interface for the existing FunPay Vertex engine. The project keeps Vertex as the account/API layer and runs it in a separate process so network polling does not freeze the Qt interface.

## Quick installation (Windows 11)

1. Install **Python 3.11** (enable the Python Launcher during setup).
2. Double-click `InstallDesktop.bat` in the repository root.
3. Run the original `Start.bat` once and complete the Vertex first-run setup.
4. Double-click `RunDesktop.bat`.

The installer creates `desktop/.venv` and installs the desktop dependencies locally. It does not copy account credentials into the repository. Vertex's configuration remains in the root `configs` directory.

## Manual installation

Open PowerShell in the repository root:

```powershell
cd desktop
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e .

# Return to the repository root and complete Vertex setup.
cd ..
Start.bat
```

After setup, launch the desktop app from the same activated environment:

```powershell
cd desktop
python -m desktop
```

## Included features

- **Connection and status:** starts Vertex in a child process, displays the account name, current connection state, lot count, and recent events.
- **Orders:** loads sales from FunPay, local text search, order details, buyer and order fields, statuses, date, and review information.
- **Messages:** loads chat list and history, sends text after confirmation, and uploads/sends PNG, JPG, GIF, or WEBP images in private chats (10 MB limit in the desktop bridge).
- **Lots:** searches the seller's visible and discoverable private trade-page lots; displays regular and currency offers; opens public listings and native FunPay edit forms for the full category-specific fields; edits regular lot title, Russian description, price, availability, and active state; edits currency offer price, amount, and active state; deletes regular lots after a separate confirmation; sends a confirmed manual raise request for all regular lots in a selected game/category.
- **Analytics:** sales count, status breakdown, daily totals and amount summary from up to 10 pages of recent sales. The screen indicates when older pages remain.
- **Event journal:** keeps a session-only list of connection, order, message, and engine events. Clearing the journal does not affect FunPay.
- **Automation:** reads and saves Vertex's global auto-delivery, auto-response, and auto-raise switches.
- **Additional settings:** reads and saves selected Boolean preferences already present in the local Vertex configuration.

## Important behavior and limitations

- Before starting the engine, review `configs/_main.cfg`, `configs/auto_response.cfg`, and `configs/auto_delivery.cfg`. Existing enabled Vertex automations begin running when the engine starts.
- Do not run the desktop engine and the original `Start.bat` bot at the same time with the same account/configuration.
- The lot list is built from the public seller profile and the private trade pages for categories discoverable from that profile (including categories present in the previous in-memory profile). It does not exhaustively query every FunPay category. If a seller has only paused offers in a category that has never appeared in the profile, that category may not be discovered automatically.
- Manual raise requests use the standard Vertex `account.raise_lots()` method. FunPay enforces its cooldown; a running automatic raise loop may also submit requests.
- Built-in FunPay auto-delivery secrets are not displayed or edited by this interface. The quantity field is locked for these lots to avoid accidentally replacing inventory.
- Currency offers use Vertex's separate `ChipFields` API. Their title/description and deletion are not exposed by this first desktop editor; price, amount, and active state are editable.
- Analytics are a bounded sample of up to 10 pages of recent sales, not a complete lifetime accounting ledger. "Amount" is the sum of order prices in the retrieved sample; it is not net profit, payout, or current balance.
- The event journal is kept in memory for the current desktop session only.
- Real account workflows still need to be verified by running the application with the user's own FunPay account. The CI checks do not log in to FunPay or execute live account changes.

## Architecture

- `app.py`: PySide6 user interface, dialogs, tables, local search, and process controller.
- `engine_runner.py`: JSON-lines bridge, command validation, serializers, and calls into the actual Vertex/FunPayAPI objects.
- `tests/test_bridge.py`: unit tests for serializers, lot discovery, and paginated analytics.
- `.github/workflows/desktop-check.yml`: Windows CI for compilation, unit tests, and import checks.
- Existing `vertex.py`, `FunPayAPI/`, configuration loaders, and automation modules remain the account engine.

## Security and licensing

- Never commit or share FunPay session cookies, `golden_key`, Telegram tokens, or the local `configs` directory.
- Desktop commands do not serialize raw lot HTML, credentials, or FunPay auto-delivery secrets to the UI.
- The upstream Vertex code is licensed under GPL-3.0. Retain required notices and meet the license requirements for modified or redistributed versions.
- See [NOTICE.md](NOTICE.md) for attribution and modification notes.
