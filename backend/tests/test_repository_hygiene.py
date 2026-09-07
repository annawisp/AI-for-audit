import re
import subprocess
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]

IGNORED_PATHS = (
    ".env",
    ".env.production",
    "test.key",
    "uploads/fake_contract.txt",
    "client_data/fake_revenue.csv",
    "logs/test.log",
    ".venv/pyvenv.cfg",
    "backend/.pytest_cache/state",
    "frontend/node_modules/react/index.js",
    "frontend/dist/index.html",
    "frontend/tsconfig.tsbuildinfo",
)

TRACKED_EXCEPTIONS = (
    ".env.example",
    "logs/.gitkeep",
    "sample_data/.gitkeep",
    "sample_data/README.md",
)

PROHIBITED_TRACKED_PARTS = {
    ".venv",
    "node_modules",
    "dist",
    ".pytest_cache",
    ".ruff_cache",
    "uploads",
    "client_data",
}

SECRET_PATTERNS = {
    "AWS access key": re.compile(r"AKIA[0-9A-Z]{16}"),
    "private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "assigned API key": re.compile(
        r"(?im)^\s*(?:api[_-]?key|llm_api_key|password)\s*[=:]\s*[^\s#][^\r\n]*$"
    ),
}


def run_git(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *arguments],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        text=True,
        check=False,
    )


def test_sensitive_and_generated_paths_are_ignored() -> None:
    for path in IGNORED_PATHS:
        result = run_git("check-ignore", "--no-index", "-q", path)
        assert result.returncode == 0, f"Expected ignored path: {path}"


def test_required_repository_placeholders_remain_trackable() -> None:
    for path in TRACKED_EXCEPTIONS:
        result = run_git("check-ignore", "--no-index", "-q", path)
        assert result.returncode == 1, f"Expected trackable path: {path}"


def test_tracked_files_exclude_sensitive_and_generated_directories() -> None:
    result = run_git("ls-files", "-z")
    assert result.returncode == 0, result.stderr
    tracked_paths = [Path(path) for path in result.stdout.split("\0") if path]

    violations = [
        str(path)
        for path in tracked_paths
        if PROHIBITED_TRACKED_PARTS.intersection(path.parts)
        or path.name == ".env"
        or path.suffix in {".key", ".pem", ".log", ".tsbuildinfo"}
    ]
    assert violations == []


def test_tracked_text_files_contain_no_obvious_secrets() -> None:
    result = run_git("ls-files", "-z")
    assert result.returncode == 0, result.stderr
    findings: list[str] = []

    for relative_path in result.stdout.split("\0"):
        if not relative_path:
            continue
        path = REPOSITORY_ROOT / relative_path
        try:
            content = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for label, pattern in SECRET_PATTERNS.items():
            if pattern.search(content):
                findings.append(f"{relative_path}: {label}")

    assert findings == []
