"""Self-hosted signed workflow registry with publisher enrollment and revocation.

No workflow is ever executed by this service. An operator enrolls a publisher's
independently verified public key. Uploads require a per-publisher bearer token
AND a valid package signature under that key. Tokens are stored only as hashes.
Bind loopback by default; put authenticated TLS ingress in front of deployments.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import base64
import hashlib
import json
import os
import re
import secrets
import sqlite3
import tempfile
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from .marketplace import inspect_package, MAX_PACKAGE
from .models import WorkflowError, NAME_RE
from .server_limits import BoundedHTTPServer

PUBLISHER = re.compile(r"[a-z][a-z0-9_-]{2,62}\Z")
VERSION = re.compile(r"(0|[1-9][0-9]{0,4})\.(0|[1-9][0-9]{0,4})\.(0|[1-9][0-9]{0,4})\Z")
MAX_BODY = 750 * 1024


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class Registry:
    def __init__(self, directory: Path):
        self.directory = Path(directory)
        if self.directory.is_symlink():
            raise WorkflowError("registry directory cannot be a symlink")
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        if os.name != "nt":
            if self.directory.stat().st_uid != os.getuid():
                raise WorkflowError("registry directory belongs to another user")
            self.directory.chmod(0o700)
        self.db_path = self.directory / "registry.sqlite3"
        if self.db_path.is_symlink():
            raise WorkflowError("registry database cannot be a symlink")
        with self.connect() as db:
            db.executescript('''
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS publishers (
                    name TEXT PRIMARY KEY, public_key TEXT NOT NULL,
                    token_hash TEXT UNIQUE NOT NULL, revoked INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS packages (
                    publisher TEXT NOT NULL, name TEXT NOT NULL, version TEXT NOT NULL,
                    sha256 TEXT NOT NULL, manifest TEXT NOT NULL, content BLOB NOT NULL,
                    created INTEGER NOT NULL, yanked INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY(publisher,name,version));
                CREATE TABLE IF NOT EXISTS ratings (
                    reviewer TEXT NOT NULL, publisher TEXT NOT NULL, name TEXT NOT NULL,
                    stars INTEGER NOT NULL CHECK(stars BETWEEN 1 AND 5),
                    PRIMARY KEY(reviewer,publisher,name));
                CREATE TABLE IF NOT EXISTS audit (
                    created INTEGER NOT NULL, actor TEXT NOT NULL, event TEXT NOT NULL, subject TEXT NOT NULL);
            ''')
        self.db_path.chmod(0o600)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.db_path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def audit(db: sqlite3.Connection, actor: str, event: str, subject: str) -> None:
        db.execute("INSERT INTO audit VALUES (?,?,?,?)", (int(time.time()), actor, event, subject))
        db.execute("DELETE FROM audit WHERE rowid IN (SELECT rowid FROM audit ORDER BY rowid DESC LIMIT -1 OFFSET 10000)")

    def enroll(self, name: str, public_key: Path) -> str:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        if not PUBLISHER.fullmatch(name):
            raise WorkflowError("publisher must be 3-63 lowercase letters/digits, underscores or hyphens")
        if public_key.is_symlink() or public_key.stat().st_size > 4096:
            raise WorkflowError("invalid publisher key file")
        key = serialization.load_pem_public_key(public_key.read_bytes())
        if not isinstance(key, Ed25519PublicKey):
            raise WorkflowError("publisher key must be Ed25519")
        raw = key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        token = secrets.token_urlsafe(32)
        try:
            with self.connect() as db:
                db.execute("INSERT INTO publishers(name,public_key,token_hash) VALUES(?,?,?)", (name, base64.b64encode(raw).decode(), token_digest(token)))
                self.audit(db, "operator", "enroll", name)
        except sqlite3.IntegrityError as exc:
            raise WorkflowError("publisher already enrolled; do not overwrite identities") from exc
        return token

    def authenticate(self, token: str) -> str:
        if not 30 <= len(token) <= 200:
            raise WorkflowError("invalid publisher token")
        with self.connect() as db:
            row = db.execute("SELECT name FROM publishers WHERE token_hash=? AND revoked=0", (token_digest(token),)).fetchone()
        if row is None:
            raise WorkflowError("invalid or revoked publisher token")
        return row["name"]

    def rotate_token(self, name: str) -> str:
        token = secrets.token_urlsafe(32)
        with self.connect() as db:
            if not db.execute("UPDATE publishers SET token_hash=? WHERE name=? AND revoked=0", (token_digest(token),name)).rowcount:
                raise WorkflowError("publisher not found or revoked")
            self.audit(db, "operator", "rotate-token", name)
        return token

    def revoke(self, name: str) -> None:
        with self.connect() as db:
            if not db.execute("UPDATE publishers SET revoked=1 WHERE name=?", (name,)).rowcount:
                raise WorkflowError("publisher not found")
            self.audit(db, "operator", "revoke", name)

    def publish(self, token: str, version: str, content: bytes) -> dict[str, Any]:
        publisher = self.authenticate(token)
        if not VERSION.fullmatch(version) or not 0 < len(content) <= MAX_PACKAGE:
            raise WorkflowError("invalid version or package size")
        with tempfile.TemporaryDirectory(prefix="h2a-registry-") as tmp:
            path = Path(tmp) / "package.h2a.zip"
            path.write_bytes(content)
            manifest, _ = inspect_package(path)
        if manifest["packageVersion"] != 2 or manifest["publisher"] != publisher:
            raise WorkflowError("uploads require a signed package for the authenticated publisher")
        if manifest.get("releaseVersion") != version:
            raise WorkflowError("published version must match the signed releaseVersion; use pack --release-version")
        digest = hashlib.sha256(content).hexdigest()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT public_key FROM publishers WHERE name=? AND revoked=0 AND token_hash=?", (publisher,token_digest(token))).fetchone()
            if row is None or not secrets.compare_digest(row["public_key"], manifest["publicKey"]):
                raise WorkflowError("package signer is not the enrolled publisher")
            try:
                db.execute("INSERT INTO packages(publisher,name,version,sha256,manifest,content,created) VALUES(?,?,?,?,?,?,?)",
                           (publisher,manifest["name"],version,digest,json.dumps(manifest),content,int(time.time())))
            except sqlite3.IntegrityError as exc:
                raise WorkflowError("version already exists; published releases are immutable") from exc
            self.audit(db,publisher,"publish",manifest["name"]+"@"+version)
        return {"publisher":publisher,"name":manifest["name"],"version":version,"sha256":digest}

    def catalog(self, query: str = "") -> list[dict[str, Any]]:
        if len(query) > 100:
            raise WorkflowError("search query too long")
        with self.connect() as db:
            rows=db.execute("SELECT p.publisher,p.name,p.version,p.sha256,p.manifest,p.created FROM packages p JOIN publishers a ON p.publisher=a.name WHERE p.yanked=0 AND a.revoked=0 ORDER BY p.created DESC LIMIT 1000").fetchall()
            ratings=db.execute("SELECT r.publisher,r.name,avg(r.stars),count(*) FROM ratings r JOIN publishers a ON r.reviewer=a.name WHERE a.revoked=0 GROUP BY r.publisher,r.name").fetchall()
        scores={(r[0],r[1]):(r[2],r[3]) for r in ratings}
        result=[]
        for row in rows:
            manifest=json.loads(row["manifest"])
            if query.lower() not in (row["name"]+" "+manifest["description"]+" "+row["publisher"]).lower():
                continue
            score,count=scores.get((row["publisher"],row["name"]),(None,0))
            result.append({"publisher":row["publisher"],"name":row["name"],"version":row["version"],"sha256":row["sha256"],
                "description":manifest["description"],"target":manifest["target"],"publicKey":manifest["publicKey"],
                "stars":score,"reviewCount":count,"createdAt":row["created"]})
        return result

    def download(self, publisher: str, name: str, version: str) -> bytes:
        with self.connect() as db:
            row=db.execute("SELECT p.content FROM packages p JOIN publishers a ON a.name=p.publisher WHERE p.publisher=? AND p.name=? AND p.version=? AND p.yanked=0 AND a.revoked=0", (publisher,name,version)).fetchone()
        if row is None:
            raise WorkflowError("package not found or revoked")
        return bytes(row[0])

    def yank(self, token: str, name: str, version: str) -> None:
        publisher=self.authenticate(token)
        with self.connect() as db:
            if not db.execute("UPDATE packages SET yanked=1 WHERE publisher=? AND name=? AND version=?",(publisher,name,version)).rowcount:
                raise WorkflowError("package not found")
            self.audit(db,publisher,"yank",name+"@"+version)

    def rate(self, token: str, publisher: str, name: str, stars: int) -> None:
        reviewer=self.authenticate(token)
        if reviewer==publisher or type(stars) is not int or not 1<=stars<=5:
            raise WorkflowError("invalid rating or self-review")
        with self.connect() as db:
            if not db.execute("SELECT 1 FROM packages WHERE publisher=? AND name=? AND yanked=0",(publisher,name)).fetchone():
                raise WorkflowError("package not found")
            db.execute("INSERT INTO ratings VALUES(?,?,?,?) ON CONFLICT(reviewer,publisher,name) DO UPDATE SET stars=excluded.stars",(reviewer,publisher,name,stars))
            self.audit(db,reviewer,"rate",publisher+"/"+name)


class RegistryHandler(BaseHTTPRequestHandler):
    def log_message(self,*args: Any) -> None:
        return  # no credentials, package data, query strings, or input payloads in logs

    def reply(self,code: int,value: Any,kind: str = "application/json") -> None:
        data=value if isinstance(value,bytes) else json.dumps(value,ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        for key,val in {"Content-Type":kind,"Content-Length":str(len(data)),"Cache-Control":"no-store",
                        "X-Content-Type-Options":"nosniff","Content-Security-Policy":"default-src 'self'; script-src 'self'; style-src 'self'; frame-ancestors 'none'; object-src 'none'"}.items():
            self.send_header(key,val)
        self.end_headers();self.wfile.write(data)

    def trusted_origin(self) -> bool:
        expected=self.server.public_origin
        parsed=urlsplit(expected)
        return self.headers.get("Host")==parsed.netloc and self.headers.get("Origin",expected)==expected

    def do_GET(self) -> None:
        if not self.trusted_origin():
            return self.reply(403,{"error":"invalid Host/Origin"})
        route=urlsplit(self.path)
        try:
            if route.path in {"/","/registry.js","/editor.css"}:
                name,kind={"/":("registry.html","text/html; charset=utf-8"),"/registry.js":("registry.js","application/javascript"),"/editor.css":("editor.css","text/css")}[route.path]
                return self.reply(200,files("human2api").joinpath("static",name).read_bytes(),kind)
            if route.path=="/health":
                from . import __version__
                return self.reply(200,{"status":"ok","version":__version__,"service":"human2api-registry"})
            if route.path=="/v1/packages":
                query=parse_qs(route.query).get("q",[""])[0]
                return self.reply(200,{"packages":self.server.store.catalog(query)})
            parts=route.path.strip("/").split("/")
            if len(parts)==5 and parts[:2]==["v1","packages"]:
                return self.reply(200,self.server.store.download(*parts[2:]),"application/zip")
            return self.reply(404,{"error":"not found"})
        except (WorkflowError,ValueError,OSError):
            return self.reply(400,{"error":"request could not be completed"})

    def do_POST(self) -> None:
        if not self.trusted_origin():
            return self.reply(403,{"error":"invalid Host/Origin"})
        try:
            auth=self.headers.get("Authorization","")
            if not auth.startswith("Bearer "):
                return self.reply(401,{"error":"publisher authentication required"})
            token=auth[7:]
            try:
                self.server.store.authenticate(token)
            except WorkflowError:
                return self.reply(401,{"error":"invalid or revoked token"})
            if self.headers.get("Transfer-Encoding") or len(self.headers.get_all("Content-Length",[]))!=1:
                raise WorkflowError("invalid body framing")
            length=int(self.headers["Content-Length"])
            if not 0<length<=MAX_BODY:
                raise WorkflowError("invalid body size")
            self.connection.settimeout(15)
            body=json.loads(self.rfile.read(length))
            if not isinstance(body,dict):
                raise WorkflowError("body must be an object")
            path=urlsplit(self.path).path
            if path=="/v1/publish":
                result=self.server.store.publish(token,body["version"],base64.b64decode(body["package"],validate=True))
                return self.reply(201,result)
            if path=="/v1/yank":
                self.server.store.yank(token,body["name"],body["version"])
                return self.reply(200,{"yanked":True})
            if path=="/v1/ratings":
                self.server.store.rate(token,body["publisher"],body["name"],body["stars"])
                return self.reply(200,{"saved":True})
            return self.reply(404,{"error":"not found"})
        except (WorkflowError,ValueError,KeyError,TypeError,OSError):
            return self.reply(400,{"error":"invalid package, signature, scope or request"})


def make_registry(directory: Path, port: int = 8770, *, host: str = "127.0.0.1", public_origin: str | None = None) -> ThreadingHTTPServer:
    if host not in {"127.0.0.1","0.0.0.0"}:
        raise WorkflowError("registry host must be loopback or explicit container bind 0.0.0.0")
    if host=="0.0.0.0" and (public_origin is None or urlsplit(public_origin).scheme!="https"):
        raise WorkflowError("container/public binding requires an HTTPS public origin and reverse proxy")
    if public_origin:
        parsed = urlsplit(public_origin)
        if parsed.scheme not in {"https", "http"} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in {"", "/"}:
            raise WorkflowError("public origin must be a root HTTP(S) origin without credentials")
        if parsed.scheme == "http" and parsed.hostname not in {"127.0.0.1", "localhost"}:
            raise WorkflowError("non-loopback public origin requires HTTPS")
    store=Registry(directory)
    server=BoundedHTTPServer((host,port),RegistryHandler)
    server.store=store
    server.public_origin=(public_origin or f"http://127.0.0.1:{server.server_address[1]}").rstrip("/")
    return server


def main(argv: list[str] | None = None) -> int:
    parser=argparse.ArgumentParser(description="Human2API signed package registry")
    parser.add_argument("action",choices=["serve","enroll","revoke","rotate-token","backup","restore","list"])
    parser.add_argument("name",nargs="?")
    parser.add_argument("--directory",type=Path,default=Path(".h2a/registry"))
    parser.add_argument("--public-key",type=Path)
    parser.add_argument("--port",type=int,default=8770)
    parser.add_argument("--host",default="127.0.0.1")
    parser.add_argument("--public-origin")
    parser.add_argument("--file",type=Path)
    args=parser.parse_args(argv)
    try:
        if args.action=="serve":
            server=make_registry(args.directory,args.port,host=args.host,public_origin=args.public_origin)
            print("Registry:",server.public_origin)
            try: server.serve_forever()
            except KeyboardInterrupt: pass
            finally: server.server_close()
        elif args.action=="restore":
            if not args.file: raise WorkflowError("--file is required")
            from .registry_backup import restore
            restore(args.file,args.directory);print("Restored into a new private registry directory")
        else:
            store=Registry(args.directory)
            if args.action=="enroll":
                if not args.name or not args.public_key: raise WorkflowError("name and --public-key required")
                print("Save this publisher token now; it is shown once:",store.enroll(args.name,args.public_key))
            elif args.action=="backup":
                if not args.file: raise WorkflowError("--file is required")
                from .registry_backup import backup
                print("Backup SHA-256:",backup(store,args.file))
            elif args.action=="rotate-token":
                if not args.name: raise WorkflowError("publisher name required")
                print("Save this replacement token now:",store.rotate_token(args.name))
            elif args.action=="revoke":
                if not args.name: raise WorkflowError("publisher name required")
                store.revoke(args.name);print("Publisher revoked")
            else: print(json.dumps(store.catalog(),indent=2))
        return 0
    except (WorkflowError,OSError,ValueError) as exc:
        print("Registry error:",exc);return 1


if __name__=="__main__":
    raise SystemExit(main())
