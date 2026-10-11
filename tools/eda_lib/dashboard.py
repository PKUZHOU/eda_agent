"""Loopback-only, read-only dashboard. No web dependencies or external assets."""
import copy
import json
from collections import OrderedDict, deque
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from socketserver import ThreadingMixIn
import threading
import time
from urllib.parse import parse_qs, urlsplit

ASSETS = Path(__file__).resolve().parent / 'web'


class SnapshotCache:
    def __init__(self, profile, fetch, refresh=5, request_timeout=15):
        self.profile = copy.deepcopy(profile)
        self.profile.setdefault('transport', {})['request_timeout_seconds'] = request_timeout
        self.fetch = fetch
        self.refresh = refresh
        self.lock = threading.Lock()
        self.cache = OrderedDict()
        self.samples = OrderedDict()

    def snapshot(self, run_id=None, attempt=None, log=None):
        key = (run_id, attempt, log)
        with self.lock:
            previous = self.cache.get(key)
            if previous and time.monotonic() - previous[0] < self.refresh:
                return previous[1]
            response = {'connected': False, 'data': previous[1]['data'] if previous else None,
                        'last_success_at': previous[1]['last_success_at'] if previous else None,
                        'refresh_seconds': self.refresh, 'error': None}
            try:
                result = self.fetch({'action': 'monitor', 'profile': self.profile,
                                     'run_id': run_id, 'attempt': attempt, 'log': log})
                if not result['ok']:
                    raise ValueError(result.get('error', {}).get('message', 'Monitor request failed'))
                data = result['result']
                selected = data.get('selected')
                if selected:
                    resources = selected['resources']
                    sample_key = (selected['run_id'], selected['attempt'])
                    samples = self.samples.setdefault(sample_key, deque(maxlen=120))
                    cpu = None
                    if samples:
                        last = samples[-1]
                        elapsed = resources['sample_time'] - last['time']
                        if (resources['process_key'] and resources['process_key'] == last['process_key']
                                and resources['cpu_seconds'] is not None and last['cpu_seconds'] is not None
                                and elapsed > 0 and resources['cpu_seconds'] >= last['cpu_seconds']):
                            cpu = round(100 * (resources['cpu_seconds'] - last['cpu_seconds']) / elapsed, 1)
                    resources['cpu_percent'] = cpu
                    samples.append({'time': resources['sample_time'], 'cpu_percent': cpu,
                                    'cpu_seconds': resources['cpu_seconds'], 'process_key': resources['process_key'],
                                    'rss_bytes': resources['rss_bytes']})
                    resources['history'] = [{'time': s['time'], 'cpu_percent': s['cpu_percent'], 'rss_bytes': s['rss_bytes']}
                                            for s in samples]
                    self.samples.move_to_end(sample_key)
                    while len(self.samples) > 32:
                        self.samples.popitem(last=False)
                response.update(connected=True, data=data, last_success_at=data['sampled_at'])
            except Exception as error:
                # Stale data stays visible; a transport outage is not an EDA failure.
                response['error'] = str(error)[:2000]
            self.cache[key] = (time.monotonic(), response)
            self.cache.move_to_end(key)
            while len(self.cache) > 16:
                self.cache.popitem(last=False)
            return response


class DashboardServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, cache, port=8765):
        self.cache = cache
        super().__init__(('localhost', port), DashboardHandler)


class DashboardHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def send_data(self, code, data, content_type='application/json; charset=utf-8'):
        self.send_response(code)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; "
                         "connect-src 'self'; img-src 'self'; frame-ancestors 'none'; base-uri 'none'")
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def permitted(self):
        port = self.server.server_port
        allowed = {'localhost:' + str(port), self.server.server_address[0] + ':' + str(port)}
        host = self.headers.get('Host', '').lower()
        origin = self.headers.get('Origin')
        return (host in allowed and (not origin or origin in {'http://' + h for h in allowed})
                and self.headers.get('Sec-Fetch-Site') != 'cross-site')

    def do_GET(self):
        if not self.permitted():
            return self.send_data(403, b'{"error":"Local same-origin access required"}')
        parsed = urlsplit(self.path)
        assets = {'/': ('index.html', 'text/html; charset=utf-8'),
                  '/app.js': ('app.js', 'text/javascript; charset=utf-8'),
                  '/style.css': ('style.css', 'text/css; charset=utf-8')}
        if parsed.path in assets:
            filename, kind = assets[parsed.path]
            return self.send_data(200, (ASSETS / filename).read_bytes(), kind)
        if parsed.path != '/api/snapshot':
            return self.send_data(404, b'{"error":"Not found"}')
        try:
            if len(parsed.query) > 1024:
                raise ValueError('Query is too long')
            params = parse_qs(parsed.query)
            if set(params) - {'run_id', 'attempt', 'log'} or any(len(v) != 1 for v in params.values()):
                raise ValueError('Unknown or repeated query parameter')
            run_id = params.get('run_id', [None])[0]
            log = params.get('log', [None])[0]
            attempt = int(params['attempt'][0]) if params.get('attempt') else None
            if attempt is not None and attempt < 1:
                raise ValueError('attempt must be positive')
            result = self.server.cache.snapshot(run_id, attempt, log)
            self.send_data(200, json.dumps(result, ensure_ascii=False, allow_nan=False).encode())
        except (ValueError, KeyError, TypeError) as error:
            self.send_data(400, json.dumps({'error': str(error)}).encode())

    def do_POST(self):
        self.send_data(405, b'{"error":"Dashboard is read-only"}')


def serve(profile, port=8765, refresh=5, request_timeout=15):
    from eda import call
    if not 1 <= port <= 65535 or not 2 <= refresh <= 60 or not 2 <= request_timeout <= 60:
        raise ValueError('Use port 1..65535 and refresh/request-timeout 2..60 seconds')
    if not isinstance(profile, dict) or not isinstance(profile.get('run_root'), str):
        raise ValueError('Profile needs run_root')
    server = DashboardServer(SnapshotCache(profile, call, refresh, request_timeout), port)
    print('EDA dashboard: http://localhost:{}/'.format(server.server_port), flush=True)
    print('Read-only monitor. Ctrl+C stops this dashboard; EDA workers continue.', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
