"""Serveur local de test : sert dist/ avec l'en-tête CORS qu'exige Stremio
(comme GitHub Pages). Usage : uv run python -m sorties_fr.serve [port]"""

import sys
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

from . import config


class CORSHandler(SimpleHTTPRequestHandler):
    def end_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Private-Network", "true")
        super().end_headers()


def main() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    handler = partial(CORSHandler, directory=str(config.DIST_DIR))
    print(f"Installer dans Stremio : http://127.0.0.1:{port}/manifest.json")
    ThreadingHTTPServer(("127.0.0.1", port), handler).serve_forever()


if __name__ == "__main__":
    main()
