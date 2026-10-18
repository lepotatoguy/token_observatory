import datetime as dt
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from archive import Archive
from server import Store


def capture(day, value):
    return dict(at=dt.datetime.fromisoformat(day+'T12:00:00+00:00').timestamp(),
                sessions=[dict(totals=dict(total=value))], sources=[], warnings=[])


class ArchiveTests(unittest.TestCase):
    def test_daily_retention_and_reopening(self):
        with tempfile.TemporaryDirectory() as folder:
            archive=Archive(folder)
            archive.update(capture('2026-10-16',10),'first')
            archive.update(capture('2026-10-16',20),'second',force=True)
            archive.update(capture('2026-10-17',30),'third')
            reopened=Archive(folder)
            self.assertEqual(reopened.dates(),['2026-10-17','2026-10-16'])
            self.assertEqual(reopened.load('2026-10-16')['sessions'][0]['totals']['total'],20)
            self.assertEqual(reopened.load('2026-10-17')['schema_version'],1)
            self.assertEqual((Path(folder)/'2026-10-17.json').stat().st_mode & 0o777,0o600)

    def test_throttle_and_failed_write_preserve_existing_snapshot(self):
        with tempfile.TemporaryDirectory() as folder:
            archive=Archive(folder)
            archive.update(capture('2026-10-17',10),'first')
            archive.update(capture('2026-10-17',20),'second')
            self.assertEqual(archive.load('2026-10-17')['sessions'][0]['totals']['total'],10)
            with patch('archive.os.replace',side_effect=OSError('disk failure')):
                result=archive.update(capture('2026-10-17',20),'second',force=True)
            self.assertIn('JSON auto-save failed',result['error'])
            self.assertEqual(archive.load('2026-10-17')['sessions'][0]['totals']['total'],10)
            self.assertEqual(list(Path(folder).glob('*.tmp')),[])

    def test_history_survives_source_deletion(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            logs=root/'claude/projects';logs.mkdir(parents=True)
            source=logs/'session.jsonl'
            source.write_text(json.dumps(dict(type='assistant',message=dict(id='one',usage=dict(input_tokens=9,output_tokens=2))))+'\n')
            store=Store(root/'codex',root/'claude',root/'saved')
            current=store.read()
            day=current['archive']['dates'][0]
            source.unlink()
            store.read(force_save=True)
            self.assertEqual(Archive(root/'saved').load(day)['sessions'][0]['totals']['total'],11)

    def test_unsafe_dates_corruption_and_symlinks_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            archive=Archive(folder)
            for day in ['../secrets','2026-99-99','2026-1-1']:
                with self.assertRaises(ValueError):archive.load(day)
            path=Path(folder)/'2026-10-17.json'
            path.write_text('{}')
            with self.assertRaises(ValueError):archive.load('2026-10-17')
            path.unlink();path.symlink_to(Path(folder)/'private.json')
            with self.assertRaises(ValueError):archive.load('2026-10-17')


if __name__=='__main__':
    unittest.main()
