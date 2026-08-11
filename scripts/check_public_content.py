"""Fail if obvious private-environment artifacts enter this public portfolio."""

from __future__ import annotations

from pathlib import Path
import re
import sys


TEXT_SUFFIXES = {".md", ".py", ".yml", ".yaml", ".json", ".js", ".sh"}
PRIVATE_ARTIFACTS = (
    re.compile(r"(?i)\.openclaw"),
    re.compile(r"(?i)tailnet"),
    re.compile(r"(?i)credentials/"),
)
EMAIL = re.compile(r"(?i)[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}")
ALLOWED_EMAILS = {"review@example.test"}


def violations(root: Path) -> list[str]:
    found: list[str] = []
    for path in root.rglob("*"):
        if (
            ".git" in path.parts
            or path == Path(__file__).resolve()
            or path.suffix not in TEXT_SUFFIXES
        ):
            continue
        text = path.read_text(encoding="utf-8")
        for pattern in PRIVATE_ARTIFACTS:
            if pattern.search(text):
                found.append(f"{path}: private-environment marker")
        for email in EMAIL.findall(text):
            if email.lower() not in ALLOWED_EMAILS:
                found.append(f"{path}: email address ({email})")
    return found


if __name__ == "__main__":
    issues = violations(Path(__file__).resolve().parents[1])
    if issues:
        print("Public-content check failed:")
        print("\n".join(issues))
        sys.exit(1)
    print("Public-content check passed.")
