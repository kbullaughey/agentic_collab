"""Static server for the reel viewer: /viewer, /assets (game assets) and /data (reel output)."""
import http.server
import socketserver
import threading
import urllib.parse
from functools import partial
from pathlib import Path

from .config import ASSETS, VIEWER

MOUNTS_TEMPLATE = {"/viewer/": VIEWER, "/assets/": ASSETS}


class _Handler(http.server.SimpleHTTPRequestHandler):
  def __init__(self, *args, mounts=None, **kwargs):
    self.mounts = mounts
    super().__init__(*args, **kwargs)

  def translate_path(self, path):
    path = urllib.parse.unquote(urllib.parse.urlsplit(path).path)
    for prefix, root in self.mounts.items():
      if path.startswith(prefix):
        rel = Path(path[len(prefix):])
        target = (root / rel).resolve()
        if root.resolve() in target.parents or target == root.resolve():
          return str(target)
    return str(VIEWER / "__missing__")

  def do_GET(self):
    if self.path in ("/", ""):
      self.send_response(302)
      self.send_header("Location", "/viewer/index.html")
      self.end_headers()
      return
    super().do_GET()

  def end_headers(self):
    self.send_header("Cache-Control", "no-store")
    super().end_headers()

  def log_message(self, fmt, *args):
    if getattr(self.server, "verbose", True):
      super().log_message(fmt, *args)


class _Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
  daemon_threads = True
  allow_reuse_address = True


def make_server(out_dir, port, verbose=True):
  mounts = dict(MOUNTS_TEMPLATE)
  mounts["/data/"] = Path(out_dir)
  srv = _Server(("127.0.0.1", port), partial(_Handler, mounts=mounts))
  srv.verbose = verbose
  return srv


def serve(cfg, out_dir, port):
  srv = make_server(out_dir, port)
  print(f"serving reel '{cfg['name']}' at http://127.0.0.1:{port}/viewer/index.html (Ctrl-C to stop)")
  try:
    srv.serve_forever()
  except KeyboardInterrupt:
    pass


def serve_in_background(out_dir, port):
  srv = make_server(out_dir, port, verbose=False)
  threading.Thread(target=srv.serve_forever, daemon=True).start()
  return srv
