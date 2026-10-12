import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sqlite3
from urllib.parse import parse_qs, urlsplit

from archive_store import DEFAULT_DATABASE, SnapshotNotFound, StoreError, import_snapshot, load_snapshot
from import_sample import read_sample
from validate_sample import SampleError, project


ROOT = Path(__file__).resolve().parents[1]
SAMPLE_PATH = ROOT / "data/samples/story.json"
ASSETS = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/model.mjs": ("model.mjs", "text/javascript; charset=utf-8"),
    "/styles.css": ("styles.css", "text/css; charset=utf-8"),
    "/favicon.svg": ("favicon.svg", "image/svg+xml"),
}


class PrototypeHandler(BaseHTTPRequestHandler):
    server_version = "ArchivePrototype/0.1"

    def respond(self, status, payload, content_type="application/json; charset=utf-8"):
        body = payload if isinstance(payload, bytes) else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' blob: data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def trusted_request(self):
        allowed_hosts = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
        host = self.headers.get("Host", "")
        if host not in allowed_hosts:
            return False
        origin = self.headers.get("Origin")
        return origin is None or origin == f"http://{host}"

    def do_GET(self):
        if not self.trusted_request():
            self.respond(403, {"error": "仅允许同源本地原型请求。"})
            return
        if len(self.path) > 2048:
            self.respond(414, {"error": "请求过长。"})
            return
        parsed = urlsplit(self.path)
        if parsed.path in ASSETS:
            filename, content_type = ASSETS[parsed.path]
            try:
                self.respond(200, (ROOT / "web" / filename).read_bytes(), content_type)
            except OSError:
                self.respond(503, {"error": "原型资源暂不可用。"})
            return
        if parsed.path != "/api/view":
            self.respond(404, {"error": "原型中没有这个入口。"})
            return
        try:
            arguments = parse_qs(parsed.query, keep_blank_values=True, max_num_fields=9)
            if set(arguments) - {"scope", "purpose", "snapshot"}:
                raise SampleError("unknown query parameter")
            scopes = arguments.get("scope", [])
            purposes = arguments.get("purpose", ["display"])
            if not scopes or len(scopes) != len(set(scopes)) or len(purposes) != 1:
                raise SampleError("explicit unique scopes and one purpose are required")
            if purposes[0] not in ("display", "export", "external_ai"):
                raise SampleError("unknown purpose")
            snapshots = arguments.get("snapshot", [])
            if len(snapshots) > 1 or (snapshots and not snapshots[0]):
                raise SampleError("expected one nonempty snapshot")
            data = load_snapshot(self.server.database, snapshots[0] if snapshots else None)
            view = project(data, scopes, purposes[0])
            view["storage"] = "sqlite"
            self.respond(200, view)
        except SnapshotNotFound:
            self.respond(404, {"error": "指定快照不可用，未替换成其他版本。"})
        except StoreError:
            self.respond(503, {"error": "本地数据库不可用或完整性检查失败，请检查导入状态。"})
        except (SampleError, ValueError, TypeError, KeyError) as error:
            self.respond(400, {"error": "范围、用途或样本结构不符合原型契约。"})
            print(f"Prototype request rejected: {type(error).__name__}", flush=True)
        except OSError:
            self.respond(503, {"error": "无法读取本地档案，请检查数据库。"})

    def do_HEAD(self):
        self.do_GET()

    def do_POST(self):
        self.respond(405, {"error": "此原型只支持只读请求。"})

    def log_message(self, message, *arguments):
        print(f"Prototype HTTP {self.command} completed", flush=True)


def main():
    parser = argparse.ArgumentParser(description="Local-only synthetic archive prototype. Not a production server.")
    parser.add_argument("--port", type=int, default=4173)
    parser.add_argument("--database", type=Path, help="Use an existing imported SQLite database; default bootstraps the synthetic fixture once")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("port must be between 1 and 65535")
    database = (args.database or DEFAULT_DATABASE).expanduser().resolve()
    try:
        if args.database is None and not database.exists():
            import_snapshot(read_sample(SAMPLE_PATH), database)
        load_snapshot(database)
        server = ThreadingHTTPServer(("127.0.0.1", args.port), PrototypeHandler)
        server.database = database
    except (StoreError, OSError, ValueError, TypeError, KeyError, sqlite3.Error) as error:
        parser.exit(1, f"Cannot start prototype: {error}\n")
    print(f"Archive prototype: http://127.0.0.1:{server.server_port}", flush=True)
    print(f"SQLite archive: {database}", flush=True)
    print("Synthetic data only. Bound to loopback; not for public deployment. Ctrl+C to stop.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
