"""Ghost-box launcher. Run: uv run --locked --extra inference main.py."""

import sys

from ghost_box.ui.window import main


if __name__ == "__main__":
    sys.exit(main())
