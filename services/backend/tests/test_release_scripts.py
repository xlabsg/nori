import importlib.util
import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def test_demo_is_synthetic_and_refuses_existing_database(tmp_path):
    command = [sys.executable, str(ROOT / "scripts/demo.py"), "--data-dir", str(tmp_path)]
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    with sqlite3.connect(tmp_path / "finance.db") as conn:
        assert conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM conversations").fetchone()[0] == 1
        assert (
            "虚构数据"
            in conn.execute(
                "SELECT payload_json FROM chat_events WHERE type='assistant'"
            ).fetchone()[0]
        )
        before = conn.execute("SELECT COUNT(*) FROM chat_events").fetchone()[0]
    assert "No connectors, model calls or tasks" in result.stdout
    repeated = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
    assert repeated.returncode != 0
    with sqlite3.connect(tmp_path / "finance.db") as conn:
        assert conn.execute("SELECT COUNT(*) FROM chat_events").fetchone()[0] == before


def test_secret_scanner_reports_category_and_line_only():
    spec = importlib.util.spec_from_file_location("secret_check", ROOT / "scripts/check-secrets.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    fake = b"header\n" + b"GOCSPX-" + b"x" * 25
    assert module.scan(fake) == [("Google OAuth secret", 2)]
    assert module.scan(b"GOOGLE_CLIENT_SECRET=\n") == []
