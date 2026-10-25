"""Public default MovieHub channel lists; discard every stream URL immediately."""

import json
from pathlib import Path
import re
import urllib.request

from .identity import country, guide_keys, key


def parse(text, source):
    rows = []
    group = ""
    for line in text.splitlines():
        if line.startswith("#EXTGRP:"):
            group = line[8:].strip()
        if not line.startswith("#EXTINF:"):
            continue
        attrs = dict(re.findall(r'([\w-]+)="([^"]*)"', line))
        name = line.rsplit(",", 1)[-1].strip()
        identifier = attrs.get("tvg-id", "")
        match = re.search(r"\.([a-z]{2})(?:@.*)?$", identifier, re.I)
        region = country(match.group(1)) if match else ""
        label = attrs.get("group-title", group)
        if not region and source == "free-tv":
            # Free-TV groups begin with country names/codes, never use stream addresses.
            region = {"UK": "uk", "USA": "us", "Ireland": "ie", "Canada": "ca", "Australia": "au"}.get(label.split(";")[0], "")
        if not name:
            continue
        keys = guide_keys(identifier, [name], region, aliases=True) if region else []
        rows.append({"name": name, "epg_id": identifier, "country": region, "keys": keys, "list": source})
    return rows


def load(config, cache):
    rows, reports = [], []
    cache = Path(cache)
    cache.mkdir(parents=True, exist_ok=True)
    for spec in config:
        path = cache / (spec["id"] + "-inventory.json")
        try:
            req = urllib.request.Request(spec["url"], headers={"User-Agent": "MovieHub-EPG/1.0"})
            with urllib.request.urlopen(req, timeout=30) as response:
                data = response.read(12 * 1024 * 1024 + 1)
            if len(data) > 12 * 1024 * 1024:
                raise ValueError("inventory exceeds limit")
            found = parse(data.decode("utf-8-sig"), spec["id"])
            if not found:
                raise ValueError("empty inventory")
            path.write_text(json.dumps(found, ensure_ascii=False))
            reports.append({"id": spec["id"], "status": "fresh", "rows": len(found)})
        except Exception as exc:
            found = json.loads(path.read_text()) if path.exists() else []
            reports.append({"id": spec["id"], "status": "cached" if found else "failed", "error": type(exc).__name__, "rows": len(found)})
        rows.extend(found)
    # One assessed logical identity per country/id/name, not one per repeated stream URL.
    for path in cache.glob("inline-inventory-*.json"):
        native = json.loads(path.read_text())
        rows.extend(native)
        reports.append({"id": path.stem, "status": "public_provider_snapshot", "rows": len(native)})
    unique = {}
    for row in rows:
        identity = (row["country"], key(row["epg_id"]) or key(row["name"]))
        unique.setdefault(identity, row)
    return list(unique.values()), reports
