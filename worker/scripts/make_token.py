"""Create an API token. Prints the token once and the INSERT with only its hash."""

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from loopboard.auth import new_token  # noqa: E402


def q(s):
    return "NULL" if s is None else "'" + s.replace("'", "''") + "'"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True)
    ap.add_argument("--scopes", required=True)
    ap.add_argument("--source")
    a = ap.parse_args()
    token, h = new_token()
    print(f"TOKEN={token}")
    print(
        "INSERT INTO api_tokens(name, token_hash, scopes, source, created_at) VALUES "
        f"({q(a.name)}, {q(h)}, {q(a.scopes)}, {q(a.source)}, {int(time.time())});"
    )


if __name__ == "__main__":
    main()
