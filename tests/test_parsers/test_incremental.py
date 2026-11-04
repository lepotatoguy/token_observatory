from unittest.mock import patch

from backend.parsers.claude import ClaudeLog
from backend.parsers.codex import CodexLog
from backend.parsers.local_proxy import LocalProxyParser, Recorder
from backend.models.session import Session


def test_public_parser_classes_keep_complete_line_offsets(tmp_path):
    for parser in (ClaudeLog, CodexLog):
        path = tmp_path / (parser.__name__ + '.jsonl')
        path.write_bytes(b'{}\n{"unfinished":')
        log = parser(path)
        log.refresh()
        assert log.offset == 3
        log.refresh()
        assert log.offset == 3
        with path.open('ab') as source:
            source.write(b'true}\n')
        log.refresh()
        assert log.offset == path.stat().st_size


def test_proxy_cache_reparses_only_after_file_change(tmp_path):
    path = tmp_path / 'local-usage.jsonl'
    path.write_text('{}\n')
    parser = LocalProxyParser(path)
    with patch('backend.parsers.local_proxy.sessions', return_value=[]) as read:
        first = parser.read()
        assert parser.read() is first
        read.assert_called_once()
        path.write_text('{}\n{}\n')
        parser.read()
        assert read.call_count == 2


def test_local_proxy_session_preserves_typed_json_schema(tmp_path):
    path = tmp_path / 'local-usage.jsonl'
    Recorder(path).add('ollama', 'synthetic-model', 10, 2, '/api/chat', at=1793664000)
    rows = LocalProxyParser(path).read()
    assert len(rows) == 1
    Session.model_validate(rows[0])
