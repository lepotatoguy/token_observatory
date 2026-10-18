from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import build_app


@unittest.skipUnless(sys.platform == 'darwin', 'Native icon packaging requires macOS')
class AppBuildTests(unittest.TestCase):
    def test_repeated_builds_leave_one_app_with_the_logo(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name in ['server.py', 'archive.py', 'codex_usage.py', 'claude_context.py', 'index.html', 'app.js', 'style.css', 'logo.svg', 'launch-app.sh']:
                shutil.copy2(build_app.ROOT / name, root / name)
            legacy = root / 'dist/Token Observatory.app'
            (legacy / 'Contents').mkdir(parents=True)
            with (legacy / 'Contents/Info.plist').open('wb') as output:
                plistlib.dump(dict(CFBundleIdentifier=build_app.IDENTIFIER), output)
            destination = root / 'Applications/Token Observatory.app'
            native_run = subprocess.run

            def run(command, **kwargs):
                if command[0] == build_app.LSREGISTER:
                    return subprocess.CompletedProcess(command, 0)
                return native_run(command, **kwargs)

            with patch.object(build_app, 'ROOT', root), patch.object(build_app, 'DESTINATION', destination), patch('build_app.subprocess.run', side_effect=run):
                build_app.main()
                build_app.main()
            self.assertEqual(list(root.rglob('*.app')), [destination])
            with (destination / 'Contents/Info.plist').open('rb') as source:
                self.assertEqual(plistlib.load(source)['CFBundleIconFile'], 'AppIcon.icns')
            icon = destination / 'Contents/Resources/AppIcon.icns'
            self.assertTrue(icon.read_bytes().startswith(b'icns'))
            with zipfile.ZipFile(root / 'dist/Token Observatory.zip') as archive:
                self.assertIsNone(archive.testzip())
                self.assertIn('Token Observatory.app/Contents/Resources/AppIcon.icns', archive.namelist())
