import sys
import types
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ReportEngine.agent import ReportAgent  # noqa: E402


def _truncate(max_chars, logs):
    fake = types.SimpleNamespace(config=types.SimpleNamespace(REPORT_FORUM_LOG_MAX_CHARS=max_chars))
    return ReportAgent._truncate_forum_logs(fake, logs)


def test_no_limit_keeps_logs():
    logs = "a\n" * 100
    assert _truncate(0, logs) == logs
    assert _truncate(1000, logs) == logs


def test_limit_keeps_latest_whole_lines():
    logs = "".join(f"[{i:03d}] 发言{i}\n" for i in range(200))
    result = _truncate(100, logs)
    body = result.split("\n", 1)[1]
    assert "较早内容已省略" in result
    assert len(body) <= 100
    assert body.startswith("[")
    assert body.rstrip().endswith("发言199")


@pytest.mark.parametrize("value", [None, ["not", "a", "string"]])
def test_non_string_passthrough(value):
    assert _truncate(10, value) == value
