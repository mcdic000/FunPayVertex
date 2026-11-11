# FunPay Assistant Desktop

Desktop client foundation for Windows 11, built around the existing FunPay Vertex engine.

## Run on Windows

Requires Python 3.11 or newer. Open PowerShell in the repository root:

```powershell
cd desktop
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
funpay-assistant
```

The same app can be started with `python -m desktop` after installation.

## First connection

1. Run the original `Start.bat` in the repository root once and finish the Vertex first-run setup. This creates `configs/_main.cfg`.
2. Return to FunPay Assistant Desktop and press **Запустить движок**.
3. Confirm the warning. The engine will use the automation switches and settings already stored in `configs`.

When connected, the desktop process starts the existing Vertex engine in a separate child process. This keeps polling and engine worker threads away from the Qt UI thread. The home page shows the account, lot count, and a small feed of Vertex events.

**Important:** if auto-response, auto-delivery, auto-raise, or other automations are enabled in the Vertex configuration, they will run when the engine starts. Review `configs/_main.cfg`, `configs/auto_response.cfg`, and `configs/auto_delivery.cfg` before connecting.

Only one Vertex process should use the same FunPay account/configuration at a time. Do not run the desktop engine and the original `Start.bat` bot simultaneously.

## Architecture

- `app.py`: PySide6 desktop interface and child-process controller.
- `engine_runner.py`: startup adapter that loads the existing Vertex configuration, initializes the engine, and forwards selected events to the desktop.
- Existing `vertex.py`, `FunPayAPI/`, and Telegram modules remain the automation engine.

The desktop bridge currently reports connection state and a basic activity feed. Orders, chat contents, lot editing, automation settings, analytics, and notifications still need their dedicated UI/service modules.

## Security and licensing

- Never commit FunPay session cookies, `golden_key`, Telegram tokens, or other credentials.
- The existing Vertex configuration format is reused for this initial integration. Treat the local `configs` directory as sensitive and do not share it.
- The upstream Vertex code is GPL-3.0; retain its notices and meet the license requirements for modified/redistributed versions.
