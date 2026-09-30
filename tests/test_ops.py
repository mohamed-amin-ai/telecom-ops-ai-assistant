import dataclasses
import subprocess
from types import SimpleNamespace

import pytest

from app import auth, metrics


def _req(xff: str | None, peer: str = "10.0.0.9"):
    return SimpleNamespace(headers={"x-forwarded-for": xff} if xff else {},
                           client=SimpleNamespace(host=peer))


@pytest.mark.parametrize("proxies,xff,expected", [
    (0, "1.2.3.4", "10.0.0.9"),                              # header ignored when no proxy is trusted
    (1, "6.6.6.6, 203.0.113.7", "203.0.113.7"),              # rightmost is what our proxy saw
    (2, "6.6.6.6, 203.0.113.7, 10.1.1.1", "203.0.113.7"),
    (1, "", "10.0.0.9"),                                     # no header: fall back to the peer
])
def test_client_ip(monkeypatch, proxies, xff, expected):
    monkeypatch.setattr(auth, "settings", dataclasses.replace(auth.settings, trusted_proxies=proxies))
    assert auth.client_ip(_req(xff)) == expected


def test_spoofed_left_entries_cannot_pick_the_rate_limit_bucket(monkeypatch):
    monkeypatch.setattr(auth, "settings", dataclasses.replace(auth.settings, trusted_proxies=1))
    assert auth.client_ip(_req("9.9.9.9, 203.0.113.7")) == "203.0.113.7"


def test_hash_key_is_stable_and_not_the_key():
    h = auth.hash_key("abc")
    assert h == auth.hash_key("abc") and "abc" not in h and len(h) == 64


def test_role_order():
    assert auth.ROLE_RANK["operator"] < auth.ROLE_RANK["approver"] < auth.ROLE_RANK["admin"]


def test_metrics_render_exposes_expected_series():
    metrics.APPROVALS.labels("approved").inc()
    body, ctype = metrics.render()
    assert b"approvals_total" in body and b"llm_calls_total" in body and "text/plain" in ctype


def test_entrypoint_loads_listed_secret_files_only(tmp_path):
    secret = tmp_path / "s"
    secret.write_text("from-file")
    script = "scripts/entrypoint.sh"
    ok = subprocess.run(["sh", script, "sh", "-c", 'echo "$SENTRY_DSN|${LOG:-unset}"'],
                        env={"SENTRY_DSN_FILE": str(secret), "LOG_FILE": str(secret), "PATH": "/usr/bin:/bin"},
                        capture_output=True, text=True, check=False)
    assert ok.stdout.strip() == "from-file|unset"
    missing = subprocess.run(["sh", script, "true"],
                             env={"SENTRY_DSN_FILE": "/nonexistent", "PATH": "/usr/bin:/bin"},
                             capture_output=True, text=True, check=False)
    assert missing.returncode == 1
