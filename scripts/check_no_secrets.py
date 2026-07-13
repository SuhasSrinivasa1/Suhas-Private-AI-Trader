#!/usr/bin/env python3
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED_DIRS = {".git", ".venv", "venv", "node_modules", ".runtime", "__pycache__", ".pytest_cache"}
EXCLUDED_FILES = {"backend/.env", "local.runtime.json"}
TEXT_SUFFIXES = {".py", ".js", ".html", ".css", ".json", ".md", ".txt", ".yml", ".yaml", ".toml", ".sh", ".command"}

HIGH_RISK_PATTERNS = {
    "private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "GitHub token": re.compile(r"\b(?:ghp|github_pat)_[A-Za-z0-9_]{20,}\b"),
    "AWS access key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
}

FRONTEND_SECRET_ASSIGNMENT = re.compile(
    r"(?i)(?:api[_-]?secret|api[_-]?key|broker[_-]?(?:secret|password)|password|otp|pin|recovery[_-]?code)"
    r"\s*[:=]\s*['\"]([^'\"]{8,})['\"]"
)

PLACEHOLDER_MARKERS = ("your_", "example", "placeholder", "changeme", "replace_me", "not-a-secret")


def iter_files() -> list[Path]:
    files: list[Path] = []
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(ROOT).as_posix()
        if relative in EXCLUDED_FILES:
            continue
        if any(part in EXCLUDED_DIRS for part in path.relative_to(ROOT).parts):
            continue
        if path.suffix.lower() in TEXT_SUFFIXES or path.name in {"Brewfile", ".gitignore", ".gitattributes", ".editorconfig"}:
            files.append(path)
    return files


def main() -> None:
    findings: list[str] = []
    frontend_suffixes = {".js", ".html", ".css"}

    for path in iter_files():
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        relative = path.relative_to(ROOT).as_posix()

        for label, pattern in HIGH_RISK_PATTERNS.items():
            if pattern.search(text):
                findings.append(f"{relative}: possible {label}")

        if path.suffix.lower() in frontend_suffixes:
            for match in FRONTEND_SECRET_ASSIGNMENT.finditer(text):
                value = match.group(1).strip().lower()
                if not any(marker in value for marker in PLACEHOLDER_MARKERS):
                    findings.append(f"{relative}: possible hard-coded frontend secret assignment")

    if findings:
        print("secret leakage scan failed:")
        for finding in sorted(set(findings)):
            print(f"  - {finding}")
        raise SystemExit(1)

    print("secret leakage scan passed")


if __name__ == "__main__":
    main()
