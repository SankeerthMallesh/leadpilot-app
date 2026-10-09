"""Generate a SECRET_KEY, print it, or write it into .env."""
import re
import secrets
import sys
from pathlib import Path


def main() -> None:
    key = secrets.token_urlsafe(48)
    if "--write-env" in sys.argv:
        env = Path(".env")
        text = env.read_text()
        text = re.sub(r"^SECRET_KEY=.*$", f"SECRET_KEY={key}", text, flags=re.M)
        env.write_text(text)
    else:
        print(key)


if __name__ == "__main__":
    main()
