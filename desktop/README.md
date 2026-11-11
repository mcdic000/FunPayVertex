# FunPay Assistant Desktop

Desktop client foundation for Windows 11.

## Status

This directory is the starting point for a desktop application that will connect to the existing FunPay Vertex engine. The current commit creates documentation only; it does not yet provide a working desktop client.

## Planned architecture

- `ui/`: desktop user interface and navigation.
- `services/`: application services and orchestration.
- `integration/`: adapters around the existing FunPay Vertex / FunPayAPI code.
- `config/`: desktop-specific settings and secure credential handling.

## Development principles

1. Keep the existing Vertex engine separate from the desktop UI.
2. Do not start network polling or automate account actions until the user explicitly connects and enables the relevant feature.
3. Never store FunPay session cookies or tokens in source code or logs.
4. Preserve upstream copyright notices and GPL-3.0 licensing obligations.
5. Keep the existing Telegram interface functional while desktop functionality is added.

## Initial milestone

Build a desktop shell with navigation, connection status, safe settings storage, and a service boundary. Feature modules (orders, chat, auto-delivery, lots, analytics, notifications) will be implemented incrementally and tested against the current FunPay site behavior.
