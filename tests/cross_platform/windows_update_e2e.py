import faulthandler
faulthandler.dump_traceback_later(150, repeat=True)
import hashlib, http.server, json, os, shutil, socket, subprocess, sys, tempfile, threading, time, urllib.request
from pathlib import Path

old, new = map(Path, sys.argv[1:3])
name = 'TokenObservatory-1.5.0-windows-x64.exe'
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
        elif self.path == '/lepotatoguy/token_observatory/releases/download/v1.5.0/' + name:
            content = body
        elif self.path.endswith('/SHA256SUMS.txt'):
            content = (digest + '  ' + name + '\n').encode()
        else:
            self.send_error(404); return
        self.send_response(200); self.send_header('Content-Length', str(len(content))); self.end_headers(); self.wfile.write(content)
    def log_message(self, *args): pass

with tempfile.TemporaryDirectory(prefix='observatory-windows-upgrade-') as td:
    root = Path(td)
    (root / 'temp').mkdir()
    target = root / 'TokenObservatory.exe'
    standalone = root / 'Standalone.exe'
    shutil.copyfile(new, standalone)
    shutil.copyfile(old, target)
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]
    with http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler) as server:
        threading.Thread(target=server.serve_forever, daemon=True).start()
        env = dict(os.environ, TEMP=str(root / 'temp'), TMP=str(root / 'temp'), APPDATA=str(root / 'appdata'), USERPROFILE=str(root), TOKEN_OBSERVATORY_UPDATE_SERVER='http://127.0.0.1:%s' % server.server_port, TOKEN_OBSERVATORY_LIVE_CHECKS='0')
        def status():
            with urllib.request.urlopen('http://127.0.0.1:%s/api/update' % port, timeout=2) as response: return json.load(response)
        try:
            print('Testing new standalone executable', flush=True)
            with socket.socket() as check_sock:
                check_sock.bind(('127.0.0.1', 0)); check_port = check_sock.getsockname()[1]
            subprocess.run([str(standalone), '--no-open', '--port', str(check_port)], env=env, timeout=90, check=True)
            with urllib.request.urlopen('http://127.0.0.1:%s/api/health' % check_port, timeout=10) as response: print('Standalone health:', response.read(), flush=True)
            subprocess.run([str(standalone), '--stop', '--port', str(check_port)], env=env, timeout=30, check=True)
            print('Starting legacy app', flush=True)
            subprocess.run([str(target), '--no-open', '--port', str(port)], env=env, timeout=90, check=True)
            print('Waiting for update metadata', flush=True)
            for _ in range(90):
                try:
                    state = status()
                    if state.get('latest', {}).get('version') == '1.5.0': break
                except (OSError, AttributeError): pass
                time.sleep(1)
            else: raise RuntimeError('Legacy app did not find the test release')
            print('Starting update', flush=True)
            req = urllib.request.Request('http://127.0.0.1:%s/api/update/install' % port, data=b'{}', headers={'Content-Type':'application/json'}, method='POST')
            urllib.request.urlopen(req, timeout=10).close()
            for _ in range(180):
                try:
                    state = status()
                    if _ % 20 == 0: print('Update status:', state.get('current'), state.get('progress'), flush=True)
                    if state.get('current') == '1.5.0' and hashlib.sha256(target.read_bytes()).hexdigest() == digest:
                        print('Windows executable downloaded, verified, replaced and restarted at 1.5.0'); break
                    progress = state.get('progress') or {}
                    if progress.get('state') in ('failed', 'manual'): raise RuntimeError(str(progress))
                except OSError: pass
                time.sleep(1)
            else: raise RuntimeError('Windows update did not restart at 1.5.0')
        finally:
            for f in (target, Path(str(target) + '.old'), Path(str(target) + '.new')):
                if f.exists(): print('FILE HASH:', f.name, hashlib.sha256(f.read_bytes()).hexdigest(), 'new:', digest, flush=True)
            print('PROCESSES:', subprocess.run(['tasklist', '/v'], text=True, capture_output=True).stdout[-16000:], flush=True)
            print('Files:', [str(p.relative_to(root)) for p in root.rglob('*') if p.is_file() and (p.suffix in ('.exe', '.new', '.cmd', '.old') or p.name == 'service.log')], flush=True)
            for p in root.rglob('service.log'): print('SERVICE LOG:', p.read_text(errors='replace')[-10000:], flush=True)
            for p in root.rglob('*.cmd'): print('HELPER:', p.read_text(errors='replace')[-5000:], flush=True)
            if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest() == digest:
                print('Trying manual start of replaced executable', flush=True)
                try:
                    result = subprocess.run([str(target), '--no-open', '--port', str(port)], env=env, timeout=80, capture_output=True, text=True)
                    print('Manual start:', result.returncode, result.stdout[-2000:], result.stderr[-2000:], flush=True)
                    print('Manual status:', status(), flush=True)
                except Exception as error: print('Manual start failed:', repr(error), flush=True)
            print('Stopping app', flush=True)
            subprocess.run([str(target), '--stop', '--port', str(port)], env=env, timeout=30, check=False)
            server.shutdown()
