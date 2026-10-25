"""The same conservative name keys used by MovieHub's EpgMatch/EpgLookup.

Never remove +1, a non-London region, or infer a country from an arbitrary name.
"""

import re

QUALITY = {"hd", "uhd", "fhd", "sd", "4k", "hq", "sdi", "1080p", "720p", "576p", "480p", "360p"}
UKTV = {"dave", "davejavu", "gold", "drama", "alibi", "eden", "yesterday", "w"}
ALIASES = {
    "bbc1": "bbcone", "bbc2": "bbctwo", "itv": "itv1",
    "skysportspremiereleague": "skysportspremierleague",
    "bbconelon": "bbconelondon", "bbctwoeng": "bbctwoengland",
}


def country(code):
    return "uk" if code.lower() == "gb" else code.lower()


def key(value):
    text = (value or "").lower().split("@", 1)[0]
    text = re.sub(r"\([^)]*\)|\[[^]]*]", " ", text)
    text = re.sub(r"\.[a-z]{2}$", "", text)
    tokens = [t for t in re.split(r"[^a-z0-9+]+", text) if t and t not in QUALITY]
    if len(tokens) > 1 and tokens[-1] == "uk":
        tokens.pop()
    value = "".join(tokens)
    return ALIASES.get(value, value)


def national(value):
    if "radio" in value:
        return ""
    if value == "5":
        return "channel5"
    for name in UKTV:
        if value in {"u" + name, "uand" + name}:
            return name
    if value.endswith("london") and len(value) > 6:
        return value[:-6]
    return ""


def guide_keys(identifier, names, region, aliases=False):
    own = re.search(r"\.([a-z]{2})(?:@.*)?$", identifier.lower())
    region = country(own.group(1) if region == "mixed" and own else region)
    if not re.fullmatch(r"[a-z]{2}", region):
        return []
    if "@" in identifier:
        base, variant = identifier.split("@", 1)
        variant = key(variant)
        if variant:
            # Quality notes disappear in key(); regional/service qualifiers do not.
            return ["xmltv:" + region + ":" + key(base) + variant]
    keys = {key(identifier)}
    # Freeview's GoldRadio.uk has display-name "Gold": a radio alias cannot steal Gold TV.
    keys.update(key(n) for n in names if "radio" not in key(identifier) or "radio" in key(n))
    if region == "uk" and "channel4" in keys:
        keys.add("channel4uk")  # iptv-org explicitly labels the national feed @UK.
    radio_aliases = {
        "bbcradio5sportsxtra": "bbcradio5sportsextra",
        "bbcrasiannetwork": "bbcradioasiannetwork",
        "bbcasiannetwork": "bbcradioasiannetwork",
        "bbcworldservice": "bbcradioworldservice",
    }
    keys.update(radio_aliases[k] for k in list(keys) if k in radio_aliases)
    if aliases:
        keys.update(national(k) for k in list(keys))
    return sorted("xmltv:" + region + ":" + k for k in keys if k)


def native_key(provider, region, identifier):
    if provider == "plex":
        return "engineplex:" + identifier.rsplit("-", 1)[-1]
    if provider == "samsung":
        return "enginesamsung:" + identifier
    if provider == "xumo":
        return "enginexumo:" + identifier
    if provider == "roku":
        return "engineroku:" + identifier
    if provider == "pluto":
        return "pluto:" + identifier + "." + country(region)
    return ""
