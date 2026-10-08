# Locates the Transifex API token for the maintenance tool.
# Prefers the TX_TOKEN environment variable, then the tx CLI's ~/.transifexrc.

import configparser
import os
from pathlib import Path

TRANSIFEXRC_PATH = Path.home() / ".transifexrc"
TRANSIFEXRC_SECTION = "https://www.transifex.com"


def find_token(environ: os._Environ | dict = os.environ, transifexrc: Path = TRANSIFEXRC_PATH) -> str | None:
    return environ.get("TX_TOKEN") or _transifexrc_token(transifexrc)


def _transifexrc_token(path: Path) -> str | None:
    """Reads the token from a tx CLI config, which stores it as `token` or, in older files, `password`."""
    config = configparser.ConfigParser(interpolation=None)
    config.read(path)
    if not config.has_section(TRANSIFEXRC_SECTION):
        return None
    section = config[TRANSIFEXRC_SECTION]
    return section.get("token") or section.get("password")
