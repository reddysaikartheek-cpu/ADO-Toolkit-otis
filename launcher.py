# -*- coding: utf-8 -*-

"""
Entry point for the packaged .exe. Starts the Streamlit app and opens it in the browser.
Config (config.json) and generated Excel files are read/written next to the .exe.
"""

import os
import sys
from pathlib import Path

from streamlit.web import cli as stcli


def main() -> None:
    if getattr(sys, "frozen", False):
        base_dir = Path(sys.executable).parent
        app_path = Path(sys._MEIPASS) / "app.py"
    else:
        base_dir = Path(__file__).parent
        app_path = base_dir / "app.py"

    os.chdir(base_dir)
    sys.argv = ["streamlit", "run", str(app_path), "--global.developmentMode=false", "--server.enableCORS=true"]
    sys.exit(stcli.main())


if __name__ == "__main__":
    main()
