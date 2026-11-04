import gzip
import json
import os
import pytest

from backend.services.archive import Archive


def test_gzip_migration_retains_deleted_legacy_sources_and_one_visible_day(tmp_path):
    legacy = {'at': 1793664000, 'sessions': [{'id': 'old', 'source': 'deleted.jsonl'}]}
    archive = Archive(tmp_path)
    import datetime as dt
    day = dt.datetime.fromtimestamp(legacy['at']).date().isoformat()
    old_path = tmp_path / (day + '.json')
    old_path.write_text(json.dumps(legacy))
    snapshot = {'at': legacy['at'] + 1, 'sessions': [{'id': 'new', 'source': 'current.jsonl'}]}
    archive.update(snapshot, 'new', force=True)
    compressed = tmp_path / (day + '.json.gz')
    assert compressed.is_file()
    assert old_path.is_file()
    assert archive.dates() == [day]
    with gzip.open(compressed, 'rt') as source:
        assert {session['id'] for session in json.load(source)['sessions']} == {'old', 'new'}
    assert {session['id'] for session in archive.load(day)['sessions']} == {'old', 'new'}
    # A newer legacy snapshot remains authoritative when both formats exist.
    newer = {'at': snapshot['at'] + 1, 'sessions': []}
    old_path.write_text(json.dumps(newer))
    stamp = compressed.stat().st_mtime_ns + 1_000_000
    os.utime(old_path, ns=(stamp, stamp))
    assert archive.load(day) == newer


def test_truncated_gzip_reports_invalid_snapshot(tmp_path):
    path = tmp_path / '2026-11-03.json.gz'
    path.write_bytes(gzip.compress(b'{}')[:-4])
    with pytest.raises(ValueError, match='Truncated'):
        Archive(tmp_path).load('2026-11-03')
