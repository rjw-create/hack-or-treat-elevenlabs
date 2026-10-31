"""Serve the repo root for the player page, with HTTP Range support so the audio can seek.

python -m http.server always sends the whole file (200), and Chrome cannot seek in audio from a
server like that, so chapters, line clicks and the before/after toggle would all jump to 0:00.
Standard library only.

Usage, from the repo root: python -m web.serve [port]   then open http://127.0.0.1:8000/web/
"""
import os
import re
import sys
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BYTE_RANGE = re.compile(r"^bytes=(\d*)-(\d*)$")
CHUNK_BYTES = 64 * 1024


class RangeHandler(SimpleHTTPRequestHandler):
    def send_head(self):
        match = BYTE_RANGE.match(self.headers.get("Range", ""))
        path = self.translate_path(self.path)
        if not match or not os.path.isfile(path):
            return super().send_head()

        size = os.path.getsize(path)
        first, last = match.groups()
        if first:
            start, end = int(first), int(last) if last else size - 1
        elif last:  # "bytes=-N" means the last N bytes
            start, end = max(0, size - int(last)), size - 1
        else:
            return super().send_head()
        end = min(end, size - 1)
        if start > end:
            self.send_response(416)
            self.send_header("Content-Range", f"bytes */{size}")
            self.end_headers()
            return None

        f = open(path, "rb")
        f.seek(start)
        self.send_response(206)
        self.send_header("Content-Type", self.guess_type(path))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("Content-Length", str(end - start + 1))
        self.end_headers()
        self._range_left = end - start + 1
        return f

    def copyfile(self, source, outputfile):
        left = getattr(self, "_range_left", None)
        if left is None:
            return super().copyfile(source, outputfile)
        while left > 0:
            chunk = source.read(min(CHUNK_BYTES, left))
            if not chunk:
                break
            outputfile.write(chunk)
            left -= len(chunk)

    def end_headers(self):
        if not self.headers.get("Range"):
            self.send_header("Accept-Ranges", "bytes")
        super().end_headers()


def main(argv):
    port = int(argv[0]) if argv else 8000
    handler = partial(RangeHandler, directory=str(REPO_ROOT))
    # 127.0.0.1 only: this is a dev server, not something to expose on the network.
    with ThreadingHTTPServer(("127.0.0.1", port), handler) as server:
        print(f"serving {REPO_ROOT} at http://127.0.0.1:{port}/web/ (Ctrl+C to stop)")
        server.serve_forever()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
