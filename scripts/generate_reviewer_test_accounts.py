"""Generate STAGING-ONLY reviewer credentials privately on your own computer.

Run locally: python scripts/generate_reviewer_test_accounts.py
No network, no GitHub API, no money, and no passwords in source or terminal output.
Copy each generated JSON file to its separately designated secret setting.
Do NOT commit or share either output file.
"""
import base64
import getpass
import hashlib
import json
import os
from pathlib import Path
import secrets
import stat

PERSONAS = {
    "Student": ("test-student-https", "00000000-0000-4000-8000-000000000001"),
    "Faculty": ("test-faculty-https", "00000000-0000-4000-8000-000000000003"),
    "Coordinator": ("test-coordinator-https", "00000000-0000-4000-8000-000000000008"),
    "HOD": ("test-hod-https", "00000000-0000-4000-8000-000000000004"),
    "Admin": ("test-admin-https", "00000000-0000-4000-8000-000000000012"),
}


def salted_hash(password):
    salt = secrets.token_urlsafe(16)
    iterations = 1000000
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), iterations)
    return "pbkdf2_sha256$" + str(iterations) + "$" + salt + "$" + base64.b64encode(digest).decode()


def private_output(path, data):
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2)
        handle.write("\n")
    if os.name != "nt":
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)


def main():
    root = Path.home() / ".smartpro-reviewer-private"
    root.mkdir(mode=0o700, exist_ok=True)
    if os.name != "nt":
        os.chmod(root, 0o700)
    render_file = root / "render-reviewer-test-accounts.json"
    actions_file = root / "github-actions-test-accounts.json"
    if render_file.exists() or actions_file.exists():
        raise SystemExit("Existing private credentials found. Move/secure them before regenerating.")
    render = {}
    github = {}
    print("Creating FIVE private staging-only aliases. Passwords are never displayed.")
    for role, (alias, actor) in PERSONAS.items():
        password = getpass.getpass(f"{role} password (at least 16 characters): ")
        if len(password) < 16:
            raise SystemExit("Password too short; no files were written")
        render[alias] = {"actor": actor, "passwordHash": salted_hash(password),
                         "label": f"Synthetic HTTPS {role}"}
        github[role] = {"alias": alias, "password": password}
    private_output(render_file, render)
    private_output(actions_file, github)
    print("Created two private JSON files outside the repository:")
    print(f"  Render setting SMARTPRO_REVIEWER_TEST_ACCOUNTS: {render_file}")
    print(f"  GitHub Actions secret SMARTPRO_HOSTED_TEST_ACCOUNTS: {actions_file}")
    print("Do not post their contents in ChatGPT, commit them, or upload them publicly.")
    print("After testing, remove the supplemental Render env var and GitHub secret.")


if __name__ == "__main__":
    main()
