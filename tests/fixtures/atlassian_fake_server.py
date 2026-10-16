"""Synthetic, loopback-only Atlassian HTTP fixture. No external services."""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading
from urllib.parse import parse_qs, urlsplit


@contextmanager
def fake_server():
    calls = []
    responses = {}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def handle_request(self):
            path = urlsplit(self.path)
            length = int(self.headers.get('Content-Length', 0))
            raw = self.rfile.read(length)
            calls.append({'method': self.command, 'path': path.path,
                          'query': parse_qs(path.query), 'authorization': self.headers.get('Authorization'),
                          'body': json.loads(raw) if raw else None})
            custom = responses.get(path.path)
            if custom:
                status, body, headers = custom(self) if callable(custom) else custom
            elif path.path.endswith('/projects'):
                start = int(parse_qs(path.query).get('start', ['0'])[0])
                status, body, headers = 200, {'values': [{'key': 'DEMO' if start == 0 else 'DOCS'}],
                                             'isLastPage': start > 0, 'nextPageStart': 7}, {}
            elif path.path.endswith('/search') and '/jira/' in path.path:
                start = int(parse_qs(path.query).get('startAt', ['0'])[0])
                status, body, headers = 200, {'issues': [{'key': f'DEMO-{start + 1}'}],
                                             'startAt': start, 'maxResults': 1, 'total': 2}, {}
            elif path.path.endswith('/content/search'):
                start = int(parse_qs(path.query).get('start', ['0'])[0])
                links = {'next': '/rest/api/content/search?cql=type%3Dpage&start=1&limit=1'} if start == 0 else {}
                status, body, headers = 200, {'results': [{'id': str(start + 1)}], 'start': start,
                                             'limit': 1, 'size': 1, '_links': links}, {}
            elif path.path.endswith('.diff'):
                status, body, headers = 200, 'diff --git a/demo.txt b/demo.txt\n+hello\n', {}
            elif self.command in ('POST', 'PUT'):
                status, body, headers = (204, '', {}) if path.path.endswith('/transitions') else (200, {'id': '42'}, {})
            else:
                status, body, headers = 200, {'ok': True}, {}
            encoded = body if isinstance(body, bytes) else (body if isinstance(body, str) else json.dumps(body)).encode()
            self.send_response(status)
            self.send_header('Content-Length', str(len(encoded)))
            for name, value in headers.items():
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(encoded)

        do_GET = do_POST = do_PUT = do_DELETE = handle_request

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': 0.01}, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}', calls, responses
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def smoke():
    import os
    import subprocess
    import sys
    import tempfile
    script = Path(__file__).resolve().parents[2] / 'skills/atlassian-onprem-safe/scripts/atlassian.sh'
    with fake_server() as (base, calls, _), tempfile.TemporaryDirectory() as directory:
        file = Path(directory) / 'tokens.env'
        file.write_text(''.join(f"{p.upper()}_BASE_URL='{base}/{p}'\n{p.upper()}_TOKEN='synthetic-smoke-{p}'\n"
                                for p in ('bitbucket', 'jira', 'confluence')))
        file.chmod(0o600)
        for product, command in [('bitbucket', ['projects']), ('jira', ['search', 'project = DEMO']),
                                 ('confluence', ['search', 'type = page'])]:
            result = subprocess.run(['bash', str(script), product, *command, '--all'],
                                    env={**os.environ, 'ATLASSIAN_CONFIG_DIR': directory, 'ATLASSIAN_PROFILE': ''},
                                    capture_output=True, text=True, check=True)
            data = json.loads(result.stdout)
            assert data['pageCount'] == 2 and data['complete']
            print(product + ': ' + json.dumps(data, separators=(',', ':')))
        assert len(calls) == 6
        print('Smoke: 3 products, 6 GET requests, no external network.')


if __name__ == '__main__':
    smoke()
