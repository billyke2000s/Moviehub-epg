"""Streaming XMLTV normalization and validation; no network, external entities or private feeds."""

from datetime import datetime, timezone
import re
from defusedxml.ElementTree import iterparse

from .fetch import BoundedXML
from .identity import guide_keys, native_key


def timestamp(value):
    if not value:
        raise ValueError("missing XMLTV time")
    value = value.strip()
    if len(value) == 14:
        value += " +0000"
    return int(datetime.strptime(value, "%Y%m%d%H%M%S %z").timestamp())


def stamp(value):
    return datetime.fromtimestamp(value, timezone.utc).strftime("%Y%m%d%H%M%S +0000")


def read(path, spec, now, from_time, to_time, consume):
    mappings = {}
    channels = {}
    total = current = future = invalid = 0
    first = last = None
    with BoundedXML(path) as stream:
        root = None
        for event, item in iterparse(stream, events=("start", "end"), forbid_dtd=False, forbid_entities=True, forbid_external=True):
            if root is None:
                if item.tag != "tv":
                    raise ValueError("not an XMLTV document")
                root = item
            if event != "end":
                continue
            if item.tag == "channel":
                identifier = item.get("id", "")
                names = [n.text.strip() for n in item.findall("display-name") if n.text and n.text.strip()]
                keys = guide_keys(identifier, names, spec["country"], spec.get("aliases", False))
                if spec.get("provider"):
                    keys.append(native_key(spec["provider"], spec["country"], identifier))
                keys = sorted(set(k for k in keys if k))
                mappings[identifier] = keys
                for key in keys:
                    channels[key] = names[0] if names else identifier
                item.clear()
                root.clear()
            elif item.tag == "programme":
                try:
                    start, stop = timestamp(item.get("start")), timestamp(item.get("stop"))
                    title = (item.findtext("title") or "").strip()
                    if stop <= start or not title or stop - start > 7 * 86400:
                        raise ValueError("invalid programme")
                    first = min(first or start, start)
                    last = max(last or stop, stop)
                    if start < to_time and stop > from_time:
                        total += 1
                        current += start <= now < stop
                        future += stop > now
                        description = (item.findtext("desc") or "").strip()[:400]
                        category = (item.findtext("category") or "").strip()[:100]
                        flags = []
                        if item.find("subtitles") is not None:
                            flags.append("S")
                        if "HD" in (item.findtext("video/quality") or "").upper():
                            flags.append("HD")
                        if item.find("new") is not None or item.find("premiere") is not None:
                            flags.append("New")
                        for key in mappings.get(item.get("channel"), []):
                            consume(key, start, stop, title[:500], description, category, "|".join(flags))
                except (ValueError, OverflowError):
                    invalid += 1
                item.clear()
                root.clear()
    if not mappings or not total or not future:
        raise ValueError("empty or expired guide")
    if invalid > max(20, total // 10):
        raise ValueError("too many malformed programme timestamps")
    return channels, {"input_channels": len(mappings), "window_programmes": total, "current_programmes": current,
                      "future_programmes": future, "invalid_programmes": invalid, "first": first, "last": last}
