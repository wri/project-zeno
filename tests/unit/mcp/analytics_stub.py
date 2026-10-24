"""A stub GNW analytics API and the pull it answers, for the tests of
pull.py (test_script) and of the gnw CLI (test_cli)."""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PARA = {
    "source": "gadm",
    "src_id": "BRA.14_1",
    "name": "Pará, Brazil",
    "subtype": "state-province",
    "bbox": [-58.9, -9.8, -46.0, 2.6],
}
# Column-oriented, in no particular order, as the analytics API returns it.
RESULT = {
    "aoi_id": ["BRA.14", "BRA.14"],
    "aoi_type": ["admin", "admin"],
    "tree_cover_loss_year": [2021, 2020],
    "area_ha": [693512.76, 805620.12],
}
METADATA = {
    "aoi": {
        "type": "admin",
        "ids": ["BRA.14"],
        "provider": "gadm",
        "version": "4.1",
    },
    "start_year": "2020",
    "end_year": "2021",
    "canopy_cover": 30,
}
BODY = {
    "aoi": {"type": "admin", "ids": ["BRA.14"]},
    "start_year": "2020",
    "end_year": "2021",
    "canopy_cover": 30,
}


class StubApi:
    """The analytics API: a POST answers pending with a link, a GET of the
    link answers the result. Records each request."""

    def __init__(self, result_id: str = "df747c81"):
        self.result_id = result_id
        self.result = RESULT
        self.metadata = METADATA
        # Polls of the result link that fail (503) before one succeeds.
        self.failed_polls = 0
        self.requests: list[dict] = []
        stub = self

        class Handler(BaseHTTPRequestHandler):
            def _answer(self, payload):
                body = json.dumps(payload).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Retry-After", "0")
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):
                length = int(self.headers["Content-Length"])
                stub.requests.append(
                    {
                        "method": "POST",
                        "path": self.path,
                        "headers": {
                            key.lower(): value
                            for key, value in self.headers.items()
                        },
                        "body": json.loads(self.rfile.read(length)),
                    }
                )
                self._answer(
                    {
                        "status": "pending",
                        "data": {
                            "link": f"{stub.url}/result/{stub.result_id}"
                        },
                    }
                )

            def do_GET(self):
                stub.requests.append({"method": "GET", "path": self.path})
                if stub.failed_polls:
                    stub.failed_polls -= 1
                    self.send_error(503)
                    return
                self._answer(
                    {
                        "status": "success",
                        "data": {
                            "status": "saved",
                            "result": stub.result,
                            "metadata": stub.metadata,
                        },
                    }
                )

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
