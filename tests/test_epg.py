import gzip
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from epg.build import build, select_programmes, validate, write_xml
from epg.identity import guide_keys, native_key
from epg.inventory import parse
from epg.xmltv import read, stamp, timestamp


NOW = timestamp("20261025043000 +0000")


def guide(name="BBC One", identifier="BBCOne.uk", start=NOW - 300, stop=NOW + 7200, title="News"):
    import html
    return (f'<tv><channel id="{identifier}"><display-name>{html.escape(name)}</display-name></channel>'
            f'<programme channel="{identifier}" start="{stamp(start)}" stop="{stamp(stop)}">'
            f'<title>{title}</title></programme></tv>').encode()


class IdentityTest(unittest.TestCase):
    def test_regions_timeshifts_countries_and_radio(self):
        self.assertIn("xmltv:uk:bbcone", guide_keys("BBCOneLondonHD.uk", ["BBC One London HD"], "uk", True))
        self.assertNotIn("xmltv:uk:bbcone", guide_keys("BBCOneEast.uk", ["BBC One East HD"], "uk", True))
        self.assertIn("xmltv:uk:e4+1", guide_keys("E4Plus1.uk", ["E4 +1 HD"], "uk", True))
        self.assertNotIn("xmltv:uk:gold", guide_keys("GoldRadio.uk", ["Gold"], "uk", True))
        self.assertIn("xmltv:uk:gold", guide_keys("UAndGold.uk", ["U&Gold"], "uk", True))
        self.assertIn("xmltv:us:example", guide_keys("Example.us", ["Example"], "mixed"))

    def test_explicit_regional_suffix_cannot_claim_national_or_other_regions(self):
        self.assertEqual(["xmltv:uk:bbconescotland"], guide_keys("BBCOne.uk@Scotland", ["BBC One"], "uk", True))
        self.assertIn("xmltv:uk:bbcone", guide_keys("BBCOne.uk@HD", ["BBC One"], "uk", True))
        self.assertEqual(["xmltv:uk:bbcearthczechia"], guide_keys("BBCEarth.uk@Czechia", ["BBC Earth"], "uk", True))

    def test_existing_bbc_radio_ids_have_exact_safe_aliases(self):
        self.assertIn("xmltv:uk:bbcradio5sportsextra", guide_keys("BBCR5SX.uk", ["BBC Radio 5 Sports Xtra"], "uk"))
        self.assertIn("xmltv:uk:bbcradioasiannetwork", guide_keys("BBCRAsianNetwork.uk", ["BBC Asian Network"], "uk"))
        self.assertIn("xmltv:uk:bbcworldservice", guide_keys("BBCWorldService.uk", ["BBC World Service"], "uk"))
        self.assertIn("xmltv:uk:bbcradioworldservice", guide_keys("BBCWorldService.uk", ["BBC World Service"], "uk"))

    def test_provider_ids(self):
        self.assertEqual("engineplex:abc", native_key("plex", "gb", "server-abc"))
        self.assertEqual("enginesamsung:GBBC1ZQ", native_key("samsung", "uk", "GBBC1ZQ"))
        self.assertEqual("pluto:abc.uk", native_key("pluto", "gb", "abc"))
        self.assertEqual("engineroku:station", native_key("roku", "mixed", "station"))
        self.assertEqual("enginexumo:99951216", native_key("xumo", "us", "99951216"))

    def test_dst_is_an_absolute_instant(self):
        self.assertEqual(timestamp("20261025013000 +0100") + 3600, timestamp("20261025013000 +0000"))
        self.assertEqual(timestamp("20261025023000 +0100"), timestamp("20261025013000 +0000"))
        with self.assertRaises(ValueError):
            timestamp("20260230120000 +0000")

    def test_national_uk_qualifier_is_not_a_regional_alias(self):
        self.assertIn("xmltv:uk:channel4uk", guide_keys("Channel4.uk", ["Channel 4"], "uk"))
        self.assertNotIn("xmltv:ie:channel4uk", guide_keys("Channel4.ie", ["Channel 4"], "ie"))

    def test_inventory_never_keeps_stream_urls(self):
        rows = parse('#EXTM3U\n#EXTINF:-1 tvg-id="BBCOne.uk",BBC One\nhttps://private.example/user/password\n', "fixture")
        self.assertEqual(1, len(rows))
        self.assertNotIn("private.example", json.dumps(rows))
        self.assertIn("xmltv:uk:bbcone", rows[0]["keys"])


class MergeTest(unittest.TestCase):
    def test_country_coverage_drop_is_not_hidden_by_a_healthy_global_total(self):
        report = {"current_channels": 10000, "programmes": 900000, "latest_programme_end": NOW + 86400,
                  "generated_at_unix": NOW, "country_coverage": {"uk": {"current": 10}}}
        rules = {"min_current_channels": 100, "min_programmes": 1000, "minimum_coverage_ratio": 0.7}
        with self.assertRaisesRegex(ValueError, "uk"):
            validate(report, {"current_channels": 10000, "country_coverage": {"uk": {"current": 100}}}, rules)
        report["country_coverage"]["uk"]["current"] = 90
        validate(report, {"current_channels": 10000, "country_coverage": {"uk": {"current": 100}}}, rules)

    def test_priority_deduplication_and_gap_fill(self):
        def row(rank, start, stop, title):
            return (rank, start, stop, title, "", "", "", "fixture")
        result = select_programmes([row(1, 10, 20, "First"), row(2, 10, 20, "Duplicate"),
                                    row(2, 15, 25, "Overlap"), row(2, 20, 30, "Next")])
        self.assertEqual(["First", "Next"], [r[3] for r in result])
        self.assertEqual([(10, 20), (20, 30)], [(r[1], r[2]) for r in result])

    def test_curated_supplement_only_emits_reviewed_keys_and_programmes(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root)/"feed.gz"
            path.write_bytes(gzip.compress(guide(identifier="technical.123", name="Latest TV", stop=NOW+12*3600)))
            spec = {"country": "uk", "only_keys": ["xmltv:uk:latesttv"]}
            rows = []
            channels, stats = read(path, spec, NOW, NOW-86400, NOW+7*86400, lambda *r: rows.append(r))
            self.assertEqual(["xmltv:uk:latesttv"], list(channels))
            self.assertEqual("xmltv:uk:latesttv", rows[0][0])
            spec["only_keys"] = ["xmltv:us:latesttv"]
            rows = []
            channels, stats = read(path, spec, NOW, NOW-86400, NOW+7*86400, lambda *r: rows.append(r))
            self.assertEqual({}, channels)
            self.assertEqual([], rows)

    def test_all_country_groups_emit_programmes_in_one_ordered_scan(self):
        import sqlite3
        with tempfile.TemporaryDirectory() as root:
            db = sqlite3.connect(":memory:")
            db.execute("CREATE TABLE programmes(channel TEXT,priority,start,stop,title,descr,category,flags,source)")
            names = {}
            for country, title in [("de", "Über den Wolken"), ("in", "समाचार"), ("nl", "Nieuws"), ("pl", "Rusz się")]:
                channel = "xmltv:" + country + ":fixture"
                names[channel] = title
                db.execute("INSERT INTO programmes VALUES(?,?,?,?,?,?,?,?,?)", (channel, 10, NOW-60, NOW+12*3600, title, "", "", "", country))
            counts, coverage = write_xml(db, names, Path(root), NOW, [])
            self.assertEqual(4, counts["programmes"])
            self.assertEqual(4, counts["current_channels"])
            self.assertEqual({"de", "in", "nl", "pl"}, set(counts["source_contributions"]))
            self.assertTrue(all(v["programmes"] == 1 for v in coverage.values()))
            db.close()

    def test_malformed_xml_and_entities_are_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "bad.gz"
            spec = {"country": "uk"}
            for data in [b'<tv><broken>', b'<!DOCTYPE tv [<!ENTITY boom "bad">]><tv>&boom;</tv>']:
                path.write_bytes(gzip.compress(data))
                with self.assertRaises(Exception):
                    read(path, spec, NOW, NOW - 86400, NOW + 7 * 86400, lambda *args: None)

    def test_failed_and_malformed_source_reuses_cache_without_leaking_partial_rows(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            cache = root / "cache"
            cache.mkdir()
            cached = cache / "one.xml.gz"
            cached.write_bytes(gzip.compress(guide(stop=NOW + 12 * 3600)))
            bad = cache / "one.candidate.gz"
            bad.write_bytes(gzip.compress(guide(title="Partial")[:-5] + b"<bad>"))
            cfg = {"sources": [{"id": "one", "country": "uk", "priority": 1}], "inventory": [],
                   "window": {"behind_days": 1, "ahead_days": 7},
                   "validation": {"min_current_channels": 1, "min_programmes": 1, "minimum_coverage_ratio": 0.7}}
            with patch("epg.build.download", return_value=(bad, {"status": "downloaded"})):
                report = build(cfg, cache, root / "out", now=NOW)
            self.assertEqual("cached_invalid_update", report["sources"][0]["status"])
            output = gzip.decompress((root / "out/epg.xml.gz").read_bytes())
            self.assertIn(b"News", output)
            self.assertNotIn(b"Partial", output)
            with patch("epg.build.download", return_value=(cached, {"status": "cached_failure", "error": "HTTP 503"})):
                report = build(cfg, cache, root / "retry", now=NOW)
            self.assertGreater(report["programmes"], 0)

    def test_evicted_actions_cache_recovers_unexpired_published_listings_without_overriding_fresh(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            published = root / "epg.xml.gz"
            published.write_bytes(gzip.compress(guide(identifier="xmltv:uk:bbcone", title="Old listing", stop=NOW+12*3600)))
            saved = published.read_bytes()
            cfg = {"sources": [{"id": "one", "country": "uk", "priority": 1}], "inventory": [],
                   "window": {"behind_days": 1, "ahead_days": 7},
                   "validation": {"min_current_channels": 1, "min_programmes": 1, "minimum_coverage_ratio": 0.7}}
            with patch("epg.build.download", return_value=(None, {"status": "failed", "error": "HTTP 503"})):
                report = build(cfg, root/"cache", root/"out", now=NOW, previous_guide=published)
            self.assertGreater(report["source_contributions"]["previous-published"]["programmes"], 0)
            self.assertIn(b"Old listing", gzip.decompress((root/"out/epg.xml.gz").read_bytes()))
            self.assertEqual(saved, published.read_bytes())
            fresh = root/"fresh.gz"
            fresh.write_bytes(gzip.compress(guide(title="Fresh listing", stop=NOW+12*3600)))
            with patch("epg.build.download", return_value=(fresh, {"status": "cached_failure"})):
                report = build(cfg, root/"cache", root/"fresh-out", now=NOW, previous_guide=published)
            data = gzip.decompress((root/"fresh-out/epg.xml.gz").read_bytes())
            self.assertIn(b"Fresh listing", data)
            self.assertNotIn(b"Old listing", data)
            self.assertEqual(saved, published.read_bytes())
            with patch("epg.build.download", return_value=(None, {"status": "failed"})):
                with self.assertRaises(ValueError):
                    build(cfg, root/"cache", root/"expired-out", now=NOW+13*3600, previous_guide=published)
            self.assertEqual(saved, published.read_bytes())

    def test_expired_cache_does_not_invent_programmes_or_replace_published_output(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            published = root / "epg.xml.gz"
            published.write_bytes(b"last working guide")
            cached = root / "expired.gz"
            cached.write_bytes(gzip.compress(guide(start=NOW - 10 * 86400, stop=NOW - 9 * 86400)))
            cfg = {"sources": [{"id": "one", "country": "uk", "priority": 1}], "inventory": [],
                   "window": {"behind_days": 1, "ahead_days": 7},
                   "validation": {"min_current_channels": 1, "min_programmes": 1, "minimum_coverage_ratio": 0.7}}
            with patch("epg.build.download", return_value=(cached, {"status": "cached_failure"})):
                with self.assertRaises(ValueError):
                    build(cfg, root / "cache", root / "out", now=NOW)
            self.assertEqual(b"last working guide", published.read_bytes())

    def test_coverage_drop_rejects_new_output(self):
        report = {"current_channels": 69, "programmes": 2000, "latest_programme_end": NOW + 86400, "generated_at_unix": NOW}
        with self.assertRaises(ValueError):
            validate(report, {"current_channels": 100}, {"min_current_channels": 1, "min_programmes": 1, "minimum_coverage_ratio": 0.7})


if __name__ == "__main__":
    unittest.main()
