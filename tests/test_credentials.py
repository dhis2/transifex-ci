# Tests for locating the Transifex API token.
# Uses real config files written to a temporary directory.

from pathlib import Path

from txadmin.credentials import find_token

FULL_RC = """[https://www.transifex.com]
api_hostname = https://api.transifex.com
hostname = https://www.transifex.com
password = rc-password
rest_hostname = https://rest.api.transifex.com
token = rc-token
username = api
"""

PASSWORD_ONLY_RC = """[https://www.transifex.com]
api_hostname = https://api.transifex.com
hostname = https://www.transifex.com
username = api
password = rc-password
"""


def write_rc(tmp_path: Path, content: str) -> Path:
    path = tmp_path / ".transifexrc"
    path.write_text(content)
    return path


def test_environment_token_takes_precedence(tmp_path):
    assert find_token({"TX_TOKEN": "env-token"}, write_rc(tmp_path, FULL_RC)) == "env-token"


def test_transifexrc_token_used_without_environment(tmp_path):
    assert find_token({}, write_rc(tmp_path, FULL_RC)) == "rc-token"


def test_transifexrc_password_used_when_no_token(tmp_path):
    assert find_token({}, write_rc(tmp_path, PASSWORD_ONLY_RC)) == "rc-password"


def test_empty_environment_token_falls_back_to_transifexrc(tmp_path):
    assert find_token({"TX_TOKEN": ""}, write_rc(tmp_path, FULL_RC)) == "rc-token"


def test_no_token_when_transifexrc_missing(tmp_path):
    assert find_token({}, tmp_path / ".transifexrc") is None


def test_no_token_when_transifexrc_has_other_host(tmp_path):
    rc = write_rc(tmp_path, "[https://example.com]\ntoken = other\n")

    assert find_token({}, rc) is None
