# Entry point for the Transifex maintenance TUI: `python -m txadmin`.
# Reads the API token from TX_TOKEN or, failing that, ~/.transifexrc.

import sys

from txadmin.app import ProjectsApp
from txadmin.client import TransifexClient
from txadmin.credentials import find_token

ORGANISATION = "hisp-uio"


def main() -> None:
    token = find_token()
    if not token:
        sys.exit("No Transifex token found: set TX_TOKEN or add a token to ~/.transifexrc.")
    ProjectsApp(TransifexClient(token, ORGANISATION)).run()


if __name__ == "__main__":
    main()
