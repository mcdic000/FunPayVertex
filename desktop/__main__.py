"""Allow launching the app with `python -m desktop`."""
from .app import main

if __name__ == "__main__":
    raise SystemExit(main())
