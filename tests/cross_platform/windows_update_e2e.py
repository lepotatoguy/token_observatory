import faulthandler
faulthandler.dump_traceback_later(150, repeat=True)
import hashlib, http.server, json, os, shutil, socket, subprocess, sys, tempfile, threading, time, urllib.request
from pathlib import Path

old, new = map(Path, sys.argv[1:3])
version = os.environ.get('TOKEN_OBSERVATORY_TEST_VERSION', '1.5.0')
name = f'TokenObservatory-{version}-windows-x64.exe'
body = new.read_bytes()
digest = hashlib.sha256(body).hexdigest()

class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        base = 'http://127.0.0.1:%s' % self.server.server_port
        prefix = base + f'/lepotatoguy/token_observatory/releases/download/v{version}/'
        if self.path.endswith('/repos/lepotatoguy/token_observatory/releases/latest'):
            content = json.dumps({'tag_name': 'v' + version, 'draft': False, 'prerelease': False, 'body': '', 'assets': [
                {'name': n, 'browser_download_url': prefix + n, 'digest': 'sha256:' + digest if n == name else None}
                for n in (name, 'SHA256SUMS.txt')]}).encode()
        elif self.path == f'/lepotatoguy/token_observatory/releases/download/v{version}/' + name:
            content = body
        elif self.path.endswith('/SHA256SUMS.txt'):
            content = (digest + '  ' + name + '\n').encode()
        else:
            self.send_error(404); return
        self.send_response(200); self.send_header('Content-Length', str(len(content))); self.end_headers(); self.wfile.write(content)
    def log_message(self, *args): pass

with tempfile.TemporaryDirectory(prefix='observatory-windows-upgrade-') as td:
    root = Path(td)
    target = root / 'TokenObservatory.exe'
    shutil.copyfile(old, target)
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]
    with http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler) as server:
        threading.Thread(target=server.serve_forever, daemon=True).start()
        env = dict(os.environ, APPDATA=str(root / 'appdata'), USERPROFILE=str(root), TOKEN_OBSERVATORY_UPDATE_SERVER='http://127.0.0.1:%s' % server.server_port, TOKEN_OBSERVATORY_LIVE_CHECKS='0')
        def status():
            with urllib.request.urlopen('http://127.0.0.1:%s/api/update' % port, timeout=2) as response: return json.load(response)
        try:
            print('Starting legacy app', flush=True)
            subprocess.run([str(target), '--no-open', '--port', str(port)], env=env, timeout=90, check=True)
            print('Waiting for update metadata', flush=True)
            for _ in range(90):
                try:
                    state = status()
                    if state.get('latest', {}).get('version') == version: break
                except (OSError, AttributeError): pass
                time.sleep(1)
            else: raise RuntimeError('Legacy app did not find the test release')
            print('Starting update', flush=True)
            req = urllib.request.Request('http://127.0.0.1:%s/api/update/install' % port, data=b'{}', headers={'Content-Type':'application/json'}, method='POST')
            urllib.request.urlopen(req, timeout=10).close()
            for _ in range(180):
                try:
                    state = status()
                    if state.get('current') == version and hashlib.sha256(target.read_bytes()).hexdigest() == digest:
                        print('Windows executable downloaded, verified, replaced and restarted at the expected version'); break
                    progress = state.get('progress') or {}
                    if progress.get('state') in ('failed', 'manual'): raise RuntimeError(str(progress))
                except OSError: pass
                time.sleep(1)
            else: raise RuntimeError('Windows update did not restart at the expected version')
        finally:
            print('Stopping app', flush=True)
            subprocess.run([str(target), '--stop', '--port', str(port)], env=env, timeout=30, check=False)
            server.shutdown()
