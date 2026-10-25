"""Bounded conditional HTTPS downloads. A failed replacement never destroys a cached feed."""

import gzip
import hashlib
import json
import os
from pathlib import Path
import time
import urllib.error
import urllib.parse
import urllib.request

MAX_DOWNLOAD = 64 * 1024 * 1024
MAX_XML = 512 * 1024 * 1024


def validate_url(url):
    value = urllib.parse.urlsplit(url)
    if value.scheme != "https" or value.username or value.password or value.query or value.fragment:
        raise ValueError("Only configured public HTTPS feed URLs without credentials or queries are accepted")
    return url


class Redirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validate_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def download(spec, directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / (spec["id"] + ".xml.gz")
    meta_path = directory / (spec["id"] + ".json")
    meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
    headers = {"User-Agent": "MovieHub-EPG/1.0 (+https://github.com/billyke2000s/Moviehub-epg)"}
    if meta.get("url") == spec["url"] and path.exists():
        if meta.get("etag"):
            headers["If-None-Match"] = meta["etag"]
        if meta.get("modified"):
            headers["If-Modified-Since"] = meta["modified"]
    else:
        meta = {}
    error = "unavailable"
    for attempt in range(3):
        try:
            req = urllib.request.Request(validate_url(spec["url"]), headers=headers)
            with urllib.request.build_opener(Redirect()).open(req, timeout=35) as response:
                raw = bytearray()
                while True:
                    chunk = response.read(65536)
                    if not chunk:
                        break
                    raw.extend(chunk)
                    if len(raw) > MAX_DOWNLOAD:
                        raise ValueError("download exceeds limit")
                # Canonical cache is gzipped regardless of upstream transfer encoding.
                body = bytes(raw)
                if body.startswith(b"\x1f\x8b"):
                    compressed = body
                else:
                    compressed = gzip.compress(body, mtime=0)
                candidate = directory / (spec["id"] + ".candidate.gz")
                candidate.write_bytes(compressed)
                return candidate, {
                    "status": "downloaded", "url": spec["url"], "etag": response.headers.get("ETag"),
                    "modified": response.headers.get("Last-Modified"), "fetched_at": int(time.time()),
                    "sha256": hashlib.sha256(compressed).hexdigest(),
                }
        except urllib.error.HTTPError as exc:
            if exc.code == 304 and path.exists():
                return path, dict(meta, status="not_modified")
            error = "HTTP " + str(exc.code)
            # A denial is a limit, not an invitation to change identities or endpoints.
            if exc.code in {401, 403, 404}:
                break
            retry = min(30, int(exc.headers.get("Retry-After", "0"))) if str(exc.headers.get("Retry-After", "")).isdigit() else 0
        except (OSError, ValueError) as exc:
            error = type(exc).__name__
            retry = 0
        if attempt < 2:
            time.sleep(max(retry, 2 ** attempt))
    return (path if path.exists() else None), dict(meta, status="cached_failure" if path.exists() else "failed", error=error)


def accept(spec, candidate, metadata, directory):
    directory = Path(directory)
    target = directory / (spec["id"] + ".xml.gz")
    if Path(candidate) != target:
        os.replace(candidate, target)
    (directory / (spec["id"] + ".json")).write_text(json.dumps(metadata, indent=2) + "\n")


class BoundedXML:
    def __init__(self, path):
        self.stream = gzip.open(path, "rb")
        self.count = 0

    def read(self, size=-1):
        data = self.stream.read(min(size, 65536) if size >= 0 else 65536)
        self.count += len(data)
        if self.count > MAX_XML:
            raise ValueError("decompressed XML exceeds limit")
        return data

    def close(self):
        self.stream.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
