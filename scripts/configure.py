"""Interactive local setup. Never prints the owner password or writes it to git."""

from pathlib import Path
import getpass
import hashlib
import secrets

root = Path(__file__).resolve().parents[1]
p = root / ".env"
text = p.read_text() if p.exists() else (root / ".env.example").read_text()
if not any(
    line.startswith("JARVIS_ADMIN_PASSWORD_HASH=") and line.split("=", 1)[1].strip()
    for line in text.splitlines()
):
    password = getpass.getpass(
        "Create your Jarvis owner password (at least 12 characters): "
    )
    if len(password) < 12:
        raise SystemExit("Use at least 12 characters.")
    if password != getpass.getpass("Confirm owner password: "):
        raise SystemExit("Passwords do not match.")
    salt = secrets.token_hex(16)
    iterations = 600000
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), bytes.fromhex(salt), iterations
    ).hex()
    value = f"pbkdf2:{iterations}:{salt}:{digest}"
    lines = [
        ("JARVIS_ADMIN_PASSWORD_HASH=" + value)
        if line.startswith("JARVIS_ADMIN_PASSWORD_HASH=")
        else line
        for line in text.splitlines()
    ]
    if not any(line.startswith("JARVIS_ADMIN_PASSWORD_HASH=") for line in lines):
        lines.append("JARVIS_ADMIN_PASSWORD_HASH=" + value)
    text = "\n".join(lines) + "\n"
p.write_text(text)
print(
    "Local configuration ready. Existing model overrides and credentials have been preserved."
)
