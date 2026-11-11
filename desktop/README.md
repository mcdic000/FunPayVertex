# FunPay Assistant Desktop

Windows desktop interface for the existing FunPay Vertex engine. The project keeps Vertex as the account/API layer and runs it in a separate process so network polling does not freeze the Qt interface.

## Quick installation (Windows 11)

1. Install **Python 3.11** (enable the Python Launcher during setup).
2. Double-click `InstallDesktop.bat` in the repository root.
3. Run the original `Start.bat` once and complete the Vertex first-run setup.
4. Close the original Vertex bot window/process so the same account is not being polled twice.
5. Double-click `RunDesktop.bat`.

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
# Close the original Vertex process after first-run setup before launching desktop.
```

After setup, launch the desktop app from the same activated environment:

```powershell
cd desktop
python -m desktop
```

## Included features

- **Connection and status:** starts Vertex in a child process, displays the account name, current connection state, lot count, and recent events.
- **Orders:** loads sales from FunPay page by page, supports local text search, order details, buyer and order fields, statuses, date, and review information. Seller replies to existing reviews can be written or edited from the order details dialog after confirmation.
- **Messages:** loads chat list and history, sends text after confirmation, uploads/sends PNG, JPG, GIF, or WEBP images in private chats (10 MB limit in the desktop bridge), and can show Windows tray notifications for incoming messages.
- **Lots:** searches the seller's visible and discoverable private trade-page lots; opens a searchable all-category creation wizard with native FunPay forms; displays regular and currency offers; opens public listings and native FunPay edit forms for full category-specific fields; edits regular lot title, Russian description, price, availability, and active state; edits currency offer price, amount, and active state; deletes regular lots after a separate confirmation; sends a confirmed manual raise request for all regular lots in a selected game/category.
- **Analytics:** sales count, status breakdown, daily totals and amount summary. Each request loads up to 10 pages; use "Загрузить старые продажи" repeatedly to continue through older history. Totals are merged across loaded pages.
- **Event journal and notifications:** stores the last 250 local event entries in `storage/desktop_events.jsonl`, restores them on the next launch, and can show Windows tray alerts for new orders, order status changes, and incoming messages. Clearing the journal only clears the local log; it does not affect FunPay.
- **Automation:** reads and saves Vertex's global auto-delivery, auto-response, and auto-raise switches; includes a stock-file browser/editor for `storage/products/`, new file creation, inventory line counts, and automatic backups on overwrite.
- **Additional settings:** reads and saves selected Boolean preferences already present in the local Vertex configuration. Includes in-app editors for auto-response and auto-delivery rules; Vertex's own validators run before saving, the previous file is backed up under `storage/config_backups/`, and the in-memory rule objects are refreshed without restarting the engine.

## Important behavior and limitations

- Before starting the engine, review `configs/_main.cfg`, `configs/auto_response.cfg`, and `configs/auto_delivery.cfg`. Existing enabled Vertex automations begin running when the engine starts.
- Do not run the desktop engine and the original `Start.bat` bot at the same time with the same account/configuration.
- The lot list is built from the public seller profile and the private trade pages for categories discoverable from that profile (including categories present in the previous in-memory profile). It does not exhaustively query every FunPay category. If a seller has only paused offers in a category that has never appeared in the profile, that category may not be discovered automatically.
- Manual raise requests use the standard Vertex `account.raise_lots()` method. FunPay enforces its cooldown; a running automatic raise loop may also submit requests.
- The create wizard opens FunPay's native category form in the default browser; the browser may need its own FunPay login. Saving the new listing is performed on FunPay, not by an in-app generic form.
- The stock-file editor stores one item per non-empty line in `storage/products/`. It rejects path traversal, Windows reserved names, symbolic-link folders and oversized files; overwritten files are backed up under `storage/config_backups/products/`.
- The auto-delivery rule editor checks referenced product files under `storage/products/` and requires `$product` in the response whenever a product file is selected. Keep each stock file in that folder before saving the corresponding rule.
- If a rule fails validation, the existing configuration file and live in-memory rules are left unchanged.
- Built-in FunPay auto-delivery secrets are not displayed or edited by this interface. The quantity field is locked for these lots to avoid accidentally replacing inventory.
- Currency offers use Vertex's separate `ChipFields` API. Their title/description and deletion are not exposed by this first desktop editor; price, amount, and active state are editable.
- Analytics are a bounded sample of up to 10 pages of recent sales, not a complete lifetime accounting ledger. "Amount" is the sum of order prices in the retrieved sample; it is not net profit, payout, or current balance.
- The event journal is stored locally in `storage/desktop_events.jsonl` and retains at most 250 short event descriptions. It does not store chat message bodies, session cookies, or auto-delivery secrets. Windows tray alerts are available only when the Windows notification area supports them.
- Analytics loads up to 10 pages per request; it is not capped at 10 pages overall. Continue loading older sales until the cursor is exhausted. The sum is gross order-price total, not net profit, payout, or current balance.
- The desktop can be tested with mocked FunPay API responses and Windows offscreen UI tests. A live login, real notifications, live listing changes, and real review replies still require running the app with an authenticated FunPay account; CI deliberately does not log in or mutate a real account.

## Architecture

- `app.py`: PySide6 user interface, dialogs, tables, local search, and process controller.
- `engine_runner.py`: JSON-lines bridge, command validation, serializers, and calls into the actual Vertex/FunPayAPI objects.
- `tests/test_bridge.py`: unit tests for serializers, partial configs, lot discovery, review replies, and paginated analytics.
- `tests/test_ui.py`: Windows/offscreen Qt window, event-journal persistence, order-page merging, and analytics-page aggregation tests.
- `.github/workflows/desktop-check.yml`: Windows CI for dependency installation, compilation, unit tests, imports, and a full-window smoke test.
- Existing `vertex.py`, `FunPayAPI/`, configuration loaders, and automation modules remain the account engine.

## Security and licensing

- Never commit or share FunPay session cookies, `golden_key`, Telegram tokens, or the local `configs` directory.
- Desktop commands do not serialize raw lot HTML, credentials, or FunPay auto-delivery secrets to the UI.
- The upstream Vertex code is licensed under GPL-3.0. Retain required notices and meet the license requirements for modified or redistributed versions.
- See [NOTICE.md](NOTICE.md) for attribution and modification notes.
