"""Local Bluefin preview. Run with the repository virtualenv, port 4175."""
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
import os
os.chdir(Path(__file__).resolve().parent)

class Handler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def end_headers(self):
        self.send_header('Cache-Control', 'no-store')
        super().end_headers()

    def do_GET(self):
        if self.path.startswith('/api/'):
            return self.proxy()
        if self.path.startswith('/bluefin/'):
            self.path = self.path[len('/bluefin'):]
        if self.path.split('?')[0].endswith('.html'):
            self.path = '/index.html'
        return super().do_GET()

    def do_POST(self):
        if self.path.startswith('/api/'):
            return self.proxy()
        self.send_error(404)

    def proxy(self):
        headers = {'Content-Type': 'application/json'}
        if self.headers.get('Authorization'):
            headers['Authorization'] = self.headers['Authorization']
        body = self.rfile.read(int(self.headers.get('Content-Length', 0))) or None
        request = Request('http://127.0.0.1:8000' + self.path, data=body, headers=headers, method=self.command)
        try:
            response = urlopen(request, timeout=180)
        except HTTPError as error:
            response = error
        except URLError:
            return self.send_error(502, 'Backend on port 8000 is unavailable')
        with response:
            payload = response.read()
            self.send_response(response.code)
            self.send_header('Content-Type', response.headers.get('Content-Type', 'application/json'))
            self.send_header('Content-Length', str(len(payload)))
            self.end_headers()
            try:
                self.wfile.write(payload)
            except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
                pass

if __name__ == '__main__':
    ThreadingHTTPServer(('127.0.0.1', 4175), Handler).serve_forever()
