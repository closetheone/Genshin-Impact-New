import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import sqlite3
from urllib.parse import parse_qs, urlsplit

from archive_store import DEFAULT_DATABASE, SnapshotNotFound, StoreError, import_snapshot, load_snapshot
from import_sample import read_synthetic_sample, unique_object, reject_constant
from material_archive import MaterialCapacity, material_view, selection_request
from feedback_store import FeedbackConflict, FeedbackRateLimit, submit_feedback
from ai_archive import AIArchive
from indexed_archive import indexed_view
from query_index import prepare_indexes
from skill_package import skill_zip
from graph_archive import GraphUnavailable, graph_options
from search_archive import StaleCursor, search_options
from validate_sample import SampleError, project
from check_source_admission import load_audit
from report_source_admission import build_report
from character_catalog import BATCHES as CHARACTER_BATCHES, DEFAULT_CATALOG, CatalogUnavailable, import_catalog, read_catalog


ROOT = Path(__file__).resolve().parents[1]
SAMPLE_PATH = ROOT / "data/samples/story.json"
ASSETS = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/model.mjs": ("model.mjs", "text/javascript; charset=utf-8"),
    "/materials.mjs": ("materials.mjs", "text/javascript; charset=utf-8"),
    "/styles.css": ("styles.css", "text/css; charset=utf-8"),
    "/favicon.svg": ("favicon.svg", "image/svg+xml"),
    "/real-characters.mjs": ("real-characters.mjs", "text/javascript; charset=utf-8"),
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
        if len(self.path) > 4096:
            self.respond(414, {"error": "请求过长。"})
            return
        parsed = urlsplit(self.path)
        if parsed.path == '/api/character-catalog':
            try:
                arguments = parse_qs(parsed.query, keep_blank_values=True, max_num_fields=4)
                if set(arguments) - {'catalog', 'character'} or any(len(v) != 1 or not v[0] or len(v[0]) > 160 for v in arguments.values()):
                    raise SampleError('invalid character catalog parameters')
                result = read_catalog(self.server.database.parent / 'character-catalog.sqlite3',
                                      arguments.get('catalog', [DEFAULT_CATALOG])[0], arguments.get('character', [None])[0])
                self.respond(200, result)
            except CatalogUnavailable as error:
                self.respond(404, {'error': str(error)})
            except SampleError:
                self.respond(400, {'error': '角色资料请求或数据校验失败。'})
            except (OSError, ValueError, TypeError, KeyError, sqlite3.Error):
                self.respond(503, {'error': '真实角色资料暂不可用，请检查批次导入。'})
            return
        if parsed.path == "/downloads/genshin-story-writer.zip":
            try:
                self.respond(200, skill_zip(), "application/zip")
            except (OSError, ValueError):
                self.respond(503, {"error": "Skill 包暂不可用，请检查项目文件。"})
            return
        if parsed.path in ASSETS:
            filename, content_type = ASSETS[parsed.path]
            try:
                self.respond(200, (ROOT / "web" / filename).read_bytes(), content_type)
            except OSError:
                self.respond(503, {"error": "原型资源暂不可用。"})
            return
        if parsed.path not in ("/api/view", "/api/read", "/api/search", "/api/graph", "/api/relationship", "/api/characters", "/api/character", "/api/status"):
            self.respond(404, {"error": "原型中没有这个入口。"})
            return
        try:
            arguments = parse_qs(parsed.query, keep_blank_values=True, max_num_fields=16)
            allowed = {"scope", "purpose", "snapshot"}
            if parsed.path == "/api/search":
                allowed |= {"q", "mode", "category", "speaker", "limit", "cursor"}
            elif parsed.path == "/api/graph":
                allowed |= {"center", "hops", "predicate", "condition", "page", "cursor"}
            elif parsed.path == "/api/relationship":
                allowed |= {"id"}
            elif parsed.path == "/api/characters":
                allowed |= {"q", "limit"}
            elif parsed.path == "/api/character":
                allowed |= {"id"}
            elif parsed.path == '/api/read':
                allowed |= {'id', 'cursor'}
            if set(arguments) - allowed:
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
            options = search_options(arguments) if parsed.path == "/api/search" else None
            graph_query = graph_options(arguments) if parsed.path == "/api/graph" else None
            snapshot = snapshots[0] if snapshots else None
            if parsed.path == '/api/view':
                view = project(load_snapshot(self.server.database, snapshot), scopes, purposes[0])
            else:
                with indexed_view(self.server.database, snapshot, scopes, purposes[0]) as archive:
                    if options is not None:
                        view = archive.search(options, self.server.cursor_secret)
                    elif graph_query is not None:
                        view = archive.graph(graph_query, self.server.cursor_secret)
                    elif parsed.path == '/api/status':
                        view = dict(archive.meta)
                        view["source_admission"] = build_report(
                            load_audit(ROOT / "data/source-audit.json")
                        )
                    elif parsed.path == '/api/read':
                        values = arguments.get('id', [''])
                        cursors = arguments.get('cursor', [''])
                        if len(values) != 1 or len(values[0]) > 160 or len(cursors) != 1 or len(cursors[0]) > 1024 or ('cursor' in arguments and not cursors[0]) or (cursors[0] and not snapshot):
                            raise SampleError('invalid reader parameters')
                        view = archive.reader(values[0] or None, cursors[0], self.server.cursor_secret)
                    elif parsed.path == '/api/character':
                        values = arguments.get('id', [''])
                        if len(values) != 1 or not values[0] or len(values[0]) > 160:
                            raise SampleError('invalid character id')
                        view = archive.character_detail(values[0])
                    else:
                        field = 'id' if parsed.path == '/api/relationship' else 'q'
                        values = arguments.get(field, [''])
                        if len(values) != 1 or len(values[0]) > 160 or (field == 'id' and not values[0]):
                            raise SampleError('invalid lookup parameter')
                        if field == 'id':
                            view = archive.relationship(values[0])
                        else:
                            limits = arguments.get('limit', ['20'])
                            if len(limits) != 1 or not limits[0].isdigit():
                                raise SampleError('invalid character limit')
                            view = archive.characters(values[0], int(limits[0]))
            view["storage"] = "sqlite"
            self.respond(200, view)
        except StaleCursor:
            self.respond(409, {"error": "当前可用内容已变化，旧分页已失效，请从第一页重新读取。", "code": "stale_cursor"})
        except GraphUnavailable as error:
            self.respond(404, {"error": str(error), "code": "graph_unavailable"})
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
        if not self.trusted_request():
            self.respond(403, {"error": "仅允许同源本地原型请求。"})
            return
        if self.path not in ("/api/materials", "/api/feedback", "/api/ai-tools"):
            self.respond(405, {"error": "此入口不支持提交。"})
            return
        try:
            if self.headers.get("Transfer-Encoding") or self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                raise SampleError("JSON body required")
            lengths = self.headers.get_all("Content-Length", [])
            if len(lengths) != 1 or not lengths[0].isascii() or not lengths[0].isdigit():
                raise SampleError("body length required")
            length = int(lengths[0])
            if not 0 < length <= 65536:
                self.respond(413, {"error": "提交内容超过 64 KiB 限额。"})
                return
            self.connection.settimeout(5)
            body = self.rfile.read(length)
            if len(body) != length:
                raise SampleError("incomplete body")
            payload = json.loads(body, object_pairs_hook=unique_object, parse_constant=reject_constant)
            if self.path == "/api/ai-tools":
                if not isinstance(payload, dict) or set(payload) != {"name", "arguments"}:
                    raise SampleError("expected name and arguments")
                if not getattr(self.server, "ai_archive", None):
                    self.respond(503, {"error": "AI 只读连接未启用，请由维护者指定范围后启动服务。"})
                    return
                result = self.server.ai_archive.call(payload["name"], payload["arguments"])
            elif self.path == "/api/materials":
                request = selection_request(payload)
                result = material_view(load_snapshot(self.server.database, request["snapshot"]), request)
            else:
                result = submit_feedback(payload, self.server.database.parent / "feedback.sqlite3")
            self.respond(200, result)
        except MaterialCapacity as error:
            self.respond(409, {"error": str(error), "code": "capacity"})
        except StaleCursor:
            self.respond(409, {"error": "当前可用资料已变化，旧游标失效，请从第一页重新查询。"})
        except GraphUnavailable as error:
            self.respond(404, {"error": str(error)})
        except FeedbackRateLimit as error:
            self.respond(429, {"error": str(error)})
        except FeedbackConflict as error:
            self.respond(409, {"error": str(error)})
        except SnapshotNotFound:
            self.respond(404, {"error": "清单快照不可用；已保留选中 ID，可移除或清空后重建。"})
        except (SampleError, ValueError, TypeError, KeyError, RecursionError):
            self.respond(400, {"error": "提交格式不符合契约，请检查字段和长度。"})
        except (StoreError, OSError, sqlite3.Error):
            self.respond(503, {"error": "本地存储暂不可用，未确认提交成功。请保留内容后重试。"})

    def log_message(self, message, *arguments):
        print(f"Prototype HTTP {self.command} completed", flush=True)


def main():
    parser = argparse.ArgumentParser(description="Local character facts catalog and synthetic story prototype. Not a production server.")
    parser.add_argument("--port", type=int, default=4173)
    parser.add_argument("--database", type=Path, help="Use an existing imported SQLite database; default bootstraps the synthetic fixture once")
    parser.add_argument("--ai-scope", action="append", choices=("opening", "east", "west", "later"), help="Enable read-only AI tools with this maximum scope; repeat for more scopes")
    parser.add_argument("--ai-snapshot", help="Pin AI tools to this snapshot; defaults to the active snapshot at startup")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("port must be between 1 and 65535")
    if args.ai_snapshot and not args.ai_scope:
        parser.error("--ai-snapshot requires --ai-scope")
    database = (args.database or DEFAULT_DATABASE).expanduser().resolve()
    try:
        if args.database is None and not database.exists():
            import_snapshot(read_synthetic_sample(SAMPLE_PATH), database)
        prepare_indexes(database)
        load_snapshot(database)
        for batch in CHARACTER_BATCHES:
            import_catalog(json.loads(batch.read_text()), database.parent / 'character-catalog.sqlite3')
        server = ThreadingHTTPServer(("127.0.0.1", args.port), PrototypeHandler)
        server.database = database
        server.cursor_secret = secrets.token_bytes(32)
        server.ai_archive = AIArchive(database, args.ai_snapshot, args.ai_scope, server.cursor_secret) if args.ai_scope else None
    except (StoreError, OSError, ValueError, TypeError, KeyError, sqlite3.Error) as error:
        parser.exit(1, f"Cannot start prototype: {error}\n")
    print(f"Archive prototype: http://127.0.0.1:{server.server_port}", flush=True)
    print(f"SQLite archive: {database}", flush=True)
    print("Real character basics + synthetic story archive. Bound to loopback; not for public deployment. Ctrl+C to stop.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
