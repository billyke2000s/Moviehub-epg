"""Daily merge: source-isolated transactions, gap filling, validation and staged publication."""

import argparse
from bisect import bisect_left
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import gzip
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import time
import xml.etree.ElementTree as ET

from .fetch import accept, download
from .inventory import load as load_inventory
from .xmltv import read, stamp


def select_programmes(rows):
    """Higher priority first; lower priorities fill complete gaps without inventing clipped times."""
    starts, selected = [], []
    for row in rows:
        rank, start, stop, title, description, category, flags, source = row
        at = bisect_left(starts, start)
        if at and selected[at - 1][2] > start:
            continue
        if at < len(selected) and selected[at][1] < stop:
            continue
        starts.insert(at, start)
        selected.insert(at, row)
    return selected


def validate(report, previous, rules):
    if report["current_channels"] < rules["min_current_channels"]:
        raise ValueError("too few channels with current programmes")
    if report["programmes"] < rules["min_programmes"]:
        raise ValueError("empty or unexpectedly small programme output")
    old = (previous or {}).get("current_channels", 0)
    if old and report["current_channels"] < old * rules["minimum_coverage_ratio"]:
        raise ValueError("current channel coverage fell by more than the allowed threshold")
    if report["latest_programme_end"] < report["generated_at_unix"] + 6 * 3600:
        raise ValueError("guide lacks usable future listings")


def write_xml(db, channels, out, now, source_reports):
    output = out / "epg.xml.gz"
    counts = {"channels": 0, "current_channels": 0, "future_channels": 0, "programmes": 0,
              "latest_programme_end": 0, "source_contributions": {}}
    coverage = {}
    representatives = {}
    with output.open("wb") as raw, gzip.GzipFile(filename="", fileobj=raw, mode="wb", mtime=0) as zipped:
        zipped.write(b'<?xml version="1.0" encoding="UTF-8"?>\n<tv generator-info-name="MovieHub EPG" generator-info-url="https://github.com/billyke2000s/Moviehub-epg">\n')
        # XMLTV requires all channel declarations before programmes.
        ids = [r[0] for r in db.execute("SELECT DISTINCT channel FROM programmes ORDER BY channel")]
        for identifier in ids:
            channel = ET.Element("channel", id=identifier)
            ET.SubElement(channel, "display-name").text = channels.get(identifier, identifier)
            zipped.write(ET.tostring(channel, encoding="utf-8") + b"\n")
        for identifier in ids:
            chosen = select_programmes(db.execute(
                "SELECT priority,start,stop,title,descr,category,flags,source FROM programmes WHERE channel=? ORDER BY priority,start,stop,source",
                (identifier,),
            ))
            current = any(r[1] <= now < r[2] for r in chosen)
            future = any(r[1] > now for r in chosen)
            coverage[identifier] = {"current": current, "future": future, "programmes": len(chosen)}
            if identifier in {"xmltv:uk:bbcone", "xmltv:uk:itv1", "xmltv:uk:skywitness", "xmltv:uk:skyatlantic", "xmltv:uk:gold", "xmltv:uk:skysportsmainevent", "xmltv:uk:tntsports1"}:
                representatives[identifier] = [{"start": stamp(r[1]), "stop": stamp(r[2]), "title": r[3], "source": r[7]} for r in chosen if r[2] > now][:4]
            counts["channels"] += 1
            counts["current_channels"] += current
            counts["future_channels"] += future
            for rank, start, stop, title, description, category, flags, source in chosen:
                item = ET.Element("programme", channel=identifier, start=stamp(start), stop=stamp(stop))
                ET.SubElement(item, "title").text = title
                if description:
                    ET.SubElement(item, "desc").text = description
                if category:
                    ET.SubElement(item, "category").text = category
                if "S" in flags.split("|"):
                    ET.SubElement(item, "subtitles", type="teletext")
                if "HD" in flags.split("|"):
                    ET.SubElement(ET.SubElement(item, "video"), "quality").text = "HDTV"
                if "New" in flags.split("|"):
                    ET.SubElement(item, "new")
                zipped.write(ET.tostring(item, encoding="utf-8") + b"\n")
                counts["programmes"] += 1
                counts["latest_programme_end"] = max(counts["latest_programme_end"], stop)
                contribution = counts["source_contributions"].setdefault(source, {"programmes": 0, "channels": set()})
                contribution["programmes"] += 1
                contribution["channels"].add(identifier)
        zipped.write(b"</tv>\n")
    for data in counts["source_contributions"].values():
        data["channels"] = len(data["channels"])
    counts["representative_programmes"] = representatives
    return counts, coverage


def build(config, cache, out, previous=None, now=None):
    started = time.monotonic()
    now = int(now or time.time())
    cache, out = Path(cache), Path(out)
    cache.mkdir(parents=True, exist_ok=True)
    out.mkdir(parents=True, exist_ok=True)
    start = now - config["window"]["behind_days"] * 86400
    stop = now + config["window"]["ahead_days"] * 86400
    database = out / "merge.db"
    database.unlink(missing_ok=True)
    db = sqlite3.connect(database)
    db.execute("CREATE TABLE programmes(channel TEXT,priority INTEGER,start INTEGER,stop INTEGER,title TEXT,descr TEXT,category TEXT,flags TEXT,source TEXT)")
    channels, reports = {}, []
    sources = config["sources"]
    # Network work runs four at once. Parsing/publication is deterministic in configured priority order.
    with ThreadPoolExecutor(max_workers=4) as pool:
        fetched = list(pool.map(lambda spec: download(spec, cache), sources))
    for spec, (path, metadata) in zip(sources, fetched):
        report = {"id": spec["id"], "priority": spec["priority"], **metadata}
        candidates = [path] if path else []
        cached = cache / (spec["id"] + ".xml.gz")
        if path and path != cached and cached.exists():
            candidates.append(cached)
        accepted = False
        for candidate in candidates:
            db.execute("SAVEPOINT source")
            buffered = []

            def consume(channel, a, b, title, description, category, flags):
                priority = spec["priority"]
                if spec.get("provider") and channel.startswith("xmltv:"):
                    priority = 50  # Provider FAST schedules are only a generic-name last resort.
                buffered.append((channel, priority, a, b, title, description, category, flags, spec["id"]))
                if len(buffered) >= 5000:
                    db.executemany("INSERT INTO programmes VALUES(?,?,?,?,?,?,?,?,?)", buffered)
                    buffered.clear()

            try:
                names, stats = read(candidate, spec, now, start, stop, consume)
                old_metadata = cache / (spec["id"] + ".json")
                old = json.loads(old_metadata.read_text()) if old_metadata.exists() else {}
                if candidate != cached and old.get("input_channels", 0) > 20 and stats["input_channels"] < old["input_channels"] * 0.5:
                    raise ValueError("source channel coverage dropped by more than 50 percent")
                db.executemany("INSERT INTO programmes VALUES(?,?,?,?,?,?,?,?,?)", buffered)
                db.execute("RELEASE source")
                channels.update({k: v for k, v in names.items() if k not in channels})
                report.update(stats)
                if candidate != path:
                    report.update(status="cached_invalid_update", error="invalid or depleted upstream replacement")
                elif candidate != cached:
                    accept(spec, candidate, {**metadata, **stats}, cache)
                accepted = True
                break
            except Exception as exc:
                db.execute("ROLLBACK TO source")
                db.execute("RELEASE source")
                report.update(status="invalid", error=type(exc).__name__)
                if str(exc) == "empty or expired guide":
                    report.update(error="empty or expired guide", stale_or_empty=True)
        if not accepted:
            report["status"] = "failed"
        reports.append(report)
    db.execute("CREATE INDEX by_channel ON programmes(channel,priority,start)")
    db.commit()
    counts, guide_coverage = write_xml(db, channels, out, now, reports)
    db.close()
    database.unlink(missing_ok=True)
    inventory, inventory_reports = load_inventory(config.get("inventory", []), cache)
    matched = current = future = 0
    by_country = {}
    unmatched = []
    for row in inventory:
        found = [guide_coverage[k] for k in row["keys"] if k in guide_coverage]
        matched += bool(found)
        current += any(c["current"] for c in found)
        future += any(c["future"] for c in found)
        region = by_country.setdefault(row["country"] or "unknown/provider-native", {"assessed": 0, "matched": 0, "current": 0, "future": 0})
        region["assessed"] += 1
        region["matched"] += bool(found)
        region["current"] += any(c["current"] for c in found)
        region["future"] += any(c["future"] for c in found)
        if not found:
            unmatched.append({k: row[k] for k in ["name", "epg_id", "country", "list"]})
    report = {
        "generated_at": datetime.fromtimestamp(now, timezone.utc).isoformat(), "generated_at_unix": now,
        "generation_seconds": round(time.monotonic() - started, 2), "window_start": stamp(start), "window_stop": stamp(stop),
        **counts, "sources": reports, "inventory_sources": inventory_reports,
        "assessment_scope": "Public default Free-TV and iptv-org logical identities plus available provider-native catalogue identities. Includes provider copies; private accounts and the viewer's installed database are not observable here",
        "country_coverage": by_country,
        "assessed_channels": len(inventory), "matched_channels": matched, "assessed_current_channels": current,
        "assessed_future_channels": future, "unmatched_channels": len(unmatched),
        "sha256": hashlib.sha256((out / "epg.xml.gz").read_bytes()).hexdigest(),
    }
    validate(report, previous, config["validation"])
    (out / "coverage.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    (out / "unmatched.json").write_text(json.dumps(unmatched, indent=2, ensure_ascii=False) + "\n")
    source_lines = ["| Source | Status | Input channels | Published programmes |", "| --- | --- | ---: | ---: |"]
    for source in reports:
        contribution = counts["source_contributions"].get(source["id"], {}).get("programmes", 0)
        source_lines.append(f'| {source["id"]} | {source["status"]} | {source.get("input_channels", 0)} | {contribution} |')
    text = f'''# MovieHub EPG coverage

Generated {report["generated_at"]} in {report["generation_seconds"]} seconds.

Public default-list assessment: **{len(inventory):,}** logical channel identities; **{matched:,}** matched, **{current:,}** with a current programme, **{future:,}** with future programmes; **{len(unmatched):,}** unmatched.

Output: {counts["channels"]:,} identifiers, {counts["programmes"]:,} programmes. Identifiers include explicit aliases and provider ids; this is not a count of distinct television services. Window: yesterday through seven days ahead, limited by upstream availability. Last programme ends {stamp(counts["latest_programme_end"])}.

This measures public default lists, not private accounts or the owner's installed TV database. Full gaps: [unmatched.json](unmatched.json). Detailed source freshness and contributions: [coverage.json](coverage.json).

''' + "\n".join(source_lines) + "\n"
    (out / "coverage.md").write_text(text)
    (out / "status.json").write_text(json.dumps({"status": "degraded" if any(s["status"] in {"failed", "cached_failure", "cached_invalid_update"} for s in reports) else "ok", "generated_at": report["generated_at"], "sha256": report["sha256"]}, indent=2) + "\n")
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="sources.json")
    parser.add_argument("--cache", default=".cache")
    parser.add_argument("--out", default="out")
    args = parser.parse_args()
    previous = json.loads(Path("coverage.json").read_text()) if Path("coverage.json").exists() else None
    try:
        result = build(json.loads(Path(args.config).read_text()), args.cache, args.out, previous)
        print(json.dumps({k: result[k] for k in ["generated_at", "channels", "programmes", "assessed_channels", "matched_channels", "assessed_current_channels", "unmatched_channels", "generation_seconds"]}, indent=2))
    except Exception as exc:
        Path(args.out).mkdir(parents=True, exist_ok=True)
        (Path(args.out) / "status.json").write_text(json.dumps({"status": "failed", "attempted_at": datetime.now(timezone.utc).isoformat(), "error": type(exc).__name__}, indent=2) + "\n")
        raise


if __name__ == "__main__":
    main()
