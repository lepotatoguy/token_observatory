import json, os, pathlib, shutil, socket, subprocess, sys, tarfile, tempfile, time, urllib.request
from pathlib import Path

archive = Path(sys.argv[1]).resolve()
with tempfile.TemporaryDirectory(prefix='observatory-linux-upgrade-') as td:
    home = Path(td)
    data = home / '.local/share/token-observatory'
    app = data / 'app'
    app.mkdir(parents=True)
    marker = data / 'history' / 'preservation-test'
    marker.parent.mkdir(parents=True)
    marker.write_text('preserve user data')
    with subprocess.Popen(['git', 'archive', 'v1.4.0'], stdout=subprocess.PIPE) as git:
        with tarfile.open(fileobj=git.stdout, mode='r|') as tar:
            tar.extractall(app)
        assert git.wait() == 0
    old_server = app / 'server.py'
    old_server.write_text("import sys\nfrom pathlib import Path\nimport update_install\naction, command = update_install.install_source(Path(sys.argv[1]), '1.5.0', 'source-linux', [sys.executable, __file__, *sys.argv[2:]])\nassert action == 'restart'\nupdate_install.restart(command)\n")
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    env = dict(os.environ, HOME=str(home), XDG_DATA_HOME=str(home / '.local/share'), TOKEN_OBSERVATORY_UPDATE_CHECKS='0', TOKEN_OBSERVATORY_LIVE_CHECKS='0')
    source = home / 'source.tar.gz'
    shutil.copyfile(archive, source)
    args = ['--port', str(port), '--data-dir', str(data / 'history')]
    logpath = Path(os.environ['RUNNER_TEMP']) / 'legacy-linux-collector.log'
    def run_until_healthy(command):
        with logpath.open('a') as log:
            proc = subprocess.Popen(command, env=env, stdout=log, stderr=subprocess.STDOUT)
            try:
                for _ in range(180):
                    if proc.poll() is not None:
                        raise RuntimeError('collector exited: ' + str(proc.returncode))
                    try:
                        with urllib.request.urlopen('http://127.0.0.1:%d/api/health' % port, timeout=1) as r:
                            result = json.load(r)
                        if result.get('app') == 'token-observatory':
                            return
                    except OSError:
                        pass
                    time.sleep(1)
                raise RuntimeError('collector health timed out')
            finally:
                if proc.poll() is None:
                    proc.terminate()
                    proc.wait(timeout=30)
    try:
        run_until_healthy([sys.executable, str(old_server), str(source)] + args)
        assert marker.read_text() == 'preserve user data'
        print('Legacy Python', sys.version, 'upgrade and restart passed')
        assert (app / '.venv/bin/python').is_file()
        check = "from pathlib import Path; import sys; from backend.services.update_install import kind; assert kind(False,'linux',Path(sys.argv[1]),Path(sys.argv[2])) == 'source-linux'"
        subprocess.run([str(app / '.venv/bin/python'), '-c', check, str(app), str(data)], env=dict(env, PYTHONPATH=str(app)), check=True)
        second = home / 'second.py'
        second.write_text("import sys\nfrom pathlib import Path\nsys.path.insert(0, sys.argv[2])\nfrom backend.services import update_install\nimport subprocess\noriginal_run = subprocess.run\ndef logged_run(*args, **kwargs):\n try: return original_run(*args, **kwargs)\n except subprocess.CalledProcessError as e:\n  print('INSTALLER STDERR:', e.stderr, flush=True); print('INSTALLER STDOUT:', e.stdout, flush=True); raise\nupdate_install.subprocess.run=logged_run\napp=Path(sys.argv[2]); command=[str(app/'.venv/bin/python'),str(app/'launcher.py'),'--serve',*sys.argv[3:]]\naction, command=update_install.install_source(Path(sys.argv[1]),'1.5.0','source-linux',command)\nassert action == 'restart'\nupdate_install.restart(command)\n")
        shutil.copyfile(archive, source)
        run_until_healthy([str(app / '.venv/bin/python'), str(second), str(source), str(app)] + args)
        assert marker.read_text() == 'preserve user data'
        print('Subsequent source upgrade and restart passed')
    except Exception:
        if logpath.exists(): print(logpath.read_text()[-10000:])
        raise
