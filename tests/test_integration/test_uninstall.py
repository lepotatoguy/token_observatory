import os
from pathlib import Path
import subprocess

import pytest

pytestmark = pytest.mark.skipif(os.name == "nt", reason="POSIX source uninstaller")


ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("stop_status", [0, 1])
def test_source_uninstall_stops_each_port_before_removal(tmp_path, stop_status):
    support = tmp_path / "data/token-observatory"
    application = support / "app"
    runtime = application / ".venv/bin/python"
    runtime.parent.mkdir(parents=True)
    (application / "launcher.py").write_text("# synthetic launcher\n")
    commands = tmp_path / "stop-commands.log"
    runtime.write_text(f'#!/bin/sh\nprintf "%s\\n" "$*" >> "{commands}"\nexit {stop_status}\n')
    runtime.chmod(0o755)
    (support / "history").mkdir()
    (support / "history/keep.json").write_text("{}")
    (support / "collector.pid").write_text("123")
    (support / "collector-8766.pid").write_text("456")
    result = subprocess.run(["/bin/sh", str(ROOT / "uninstall.sh")], capture_output=True, text=True,
                            env=dict(os.environ, HOME=str(tmp_path), XDG_DATA_HOME=str(tmp_path / "data"),
                                     TOKEN_OBSERVATORY_PLATFORM="Linux"))
    assert (support / "history/keep.json").exists()
    calls = commands.read_text()
    assert "--stop --port 8766" in calls
    if stop_status:
        assert result.returncode != 0
        assert application.exists()
    else:
        assert result.returncode == 0, result.stderr
        assert "--stop --port 8765" in calls
        assert not application.exists()
