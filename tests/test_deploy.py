"""scripts/deploy.sh against a fake `docker compose`: no Docker needed, so this checks the
control flow (state files, health gating, rollback), not the containers."""
import os
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "deploy.sh"

FAKE_DC = """#!/bin/bash
# log "<APP_TAG> <args>"; `exec` (the health probe) succeeds iff tag is in $HEALTHY_TAGS
echo "${APP_TAG:-unset} $*" >> "$FAKE_LOG"
if [ "$1" = "up" ]; then
  case " $HEALTHY_TAGS " in *" ${APP_TAG:-unset} "*) ;; *) exit 1;; esac  # like compose: dependency unhealthy
fi
if [ "$1" = "exec" ]; then
  case " $HEALTHY_TAGS " in *" ${APP_TAG:-unset} "*) exit 0;; *) exit 1;; esac
fi
exit 0
"""


@pytest.fixture
def env(tmp_path):
    dc = tmp_path / "dc"
    dc.write_text(FAKE_DC)
    dc.chmod(0o755)
    e = {**os.environ, "DC": str(dc), "STATE_DIR": str(tmp_path / "state"),
         "FAKE_LOG": str(tmp_path / "log"), "HEALTH_TRIES": "2", "HEALTH_SLEEP": "0",
         "HEALTHY_TAGS": ""}
    return e, tmp_path


def run(e, *args):
    return subprocess.run(["bash", str(SCRIPT), *args], check=False, env=e, capture_output=True, text=True)


def state(tmp, name):
    f = tmp / "state" / name
    return f.read_text().strip() if f.exists() else None


def test_first_deploy_records_current(env):
    e, tmp = env
    e["HEALTHY_TAGS"] = "v1"
    assert run(e, "v1").returncode == 0
    assert state(tmp, "current") == "v1" and state(tmp, "previous") is None


def test_second_deploy_records_previous(env):
    e, tmp = env
    e["HEALTHY_TAGS"] = "v1 v2"
    run(e, "v1")
    assert run(e, "v2").returncode == 0
    assert (state(tmp, "current"), state(tmp, "previous")) == ("v2", "v1")


def test_unhealthy_deploy_rolls_back_and_fails(env):
    e, tmp = env
    e["HEALTHY_TAGS"] = "v1"
    run(e, "v1")
    r = run(e, "v2")
    assert r.returncode == 1 and "rolled back to v1" in r.stdout
    assert state(tmp, "current") == "v1"  # unchanged: the bad tag never became current
    log = (tmp / "log").read_text()
    assert "v2 run --rm migrate" in log
    assert log.strip().splitlines()[-1].startswith("v1 exec")  # last action: probing v1


def test_unhealthy_first_deploy_has_nothing_to_roll_back_to(env):
    e, tmp = env
    r = run(e, "v1")
    assert r.returncode == 1 and state(tmp, "current") is None


def test_rollback_flag_swaps_current_and_previous(env):
    e, tmp = env
    e["HEALTHY_TAGS"] = "v1 v2"
    run(e, "v1")
    run(e, "v2")
    assert run(e, "--rollback").returncode == 0
    assert (state(tmp, "current"), state(tmp, "previous")) == ("v1", "v2")


def test_rollback_without_history_is_an_error(env):
    e, _ = env
    r = run(e, "--rollback")
    assert r.returncode == 2 and "no previous deploy" in r.stderr


def test_usage_error_without_tag(env):
    e, _ = env
    assert run(e).returncode != 0
