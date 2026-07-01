from __future__ import annotations

import os
import sys


if os.environ.get("LAPIS_E2E_DRIVER") == "1":
    python_path = os.environ.get("LAPIS_E2E_PYTHONPATH")
    if python_path and python_path not in sys.path:
        sys.path.insert(0, python_path)

    from lapis_anki_e2e.driver import init_driver

    init_driver()
