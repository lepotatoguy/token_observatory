import hashlib, http.server, json, os, socket, subprocess, sys, tempfile, threading, time, urllib.request
from pathlib import Path

old, new = map(Path, sys.argv[1:3])
subprocess.run(['sudo', 'dpkg', '-i', str(old)], check=True)
name = 'TokenObservatory-1.5.0-linux-amd64.deb'
body = new.read_bytes()
digest = hashlib.sha256(body).hexdigest()

class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        base = 'http://127.0.0.1:%s' % self.server.server_port
        prefix = base + '/lepotatoguy/token_observatory/releases/download/v1.5.0/'
        if self.path.endswith('/repos/lepotatoguy/token_observatory/releases/latest'):
            content = json.dumps({'tag_name': 'v1.5.0', 'draft': False, 'prerelease': False, 'body': '', 'assets': [
                {'name': n, 'browser_download_url': prefix + n, 'digest': 'sha256:' + digest if n == name else None}
                for n in (name, 'SHA256SUMS.txt')]}).encode()
        elif self.path == '/lepotatoguy/token_observatory/releases/download/v1.5.0/' + name: content = body
        elif self.path.endswith('/SHA256SUMS.txt'): content = (digest + '  ' + name + '\n').encode()
        else: self.send_error(404); return
        self.send_response(200); self.send_header('Content-Length', str(len(content))); self.end_headers(); self.wfile.write(content)
    def log_message(self, *args): pass

with tempfile.TemporaryDirectory(prefix='observatory-deb-upgrade-') as td:
    root = Path(td)
    bin_dir = root / 'bin'; bin_dir.mkdir()
    pkexec = bin_dir / 'pkexec'; pkexec.write_text('#!/bin/sh\nexec sudo "$@"\n'); pkexec.chmod(0o755)
    with socket.socket() as sock: sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]
    with http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler) as server:
        threading.Thread(target=server.serve_forever, daemon=True).start()
        env = dict(os.environ, HOME=str(root), XDG_DATA_HOME=str(root / 'data'), PATH=str(bin_dir) + os.pathsep + os.environ['PATH'], TOKEN_OBSERVATORY_UPDATE_SERVER='http://127.0.0.1:%s' % server.server_port, TOKEN_OBSERVATORY_LIVE_CHECKS='0')
        def status():
            with urllib.request.urlopen('http://127.0.0.1:%s/api/update' % port, timeout=2) as response: return json.load(response)
        try:
            subprocess.run(['/usr/bin/token-observatory', '--no-open', '--port', str(port)], env=env, timeout=90, check=True)
            for _ in range(90):
                try:
                    state = status()
                    if state.get('latest', {}).get('version') == '1.5.0': break
                except (OSError, AttributeError): pass
                time.sleep(1)
            else: raise RuntimeError('Legacy app did not find the test release')
            req = urllib.request.Request('http://127.0.0.1:%s/api/update/install' % port, data=b'{}', headers={'Content-Type':'application/json'}, method='POST')
            urllib.request.urlopen(req, timeout=10).close()
            for _ in range(180):
                try:
                    state = status()
                    if state.get('current') == '1.5.0':
                        version = subprocess.check_output(['dpkg-query', '-W', '-f=${Version}', 'token-observatory'], text=True)
                        assert version == '1.5.0', version
                        print('Linux deb downloaded, verified, installed with simulated approval, and restarted at 1.5.0'); break
                    progress = state.get('progress') or {}
                    if progress.get('state') in ('failed', 'manual'): raise RuntimeError(str(progress))
                except OSError: pass
                time.sleep(1)
            else: raise RuntimeError('Linux deb update did not restart at 1.5.0')
        finally:
            subprocess.run(['/usr/bin/token-observatory', '--stop', '--port', str(port)], env=env, timeout=30, check=False)
            server.shutdown()
