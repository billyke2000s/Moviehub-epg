# MovieHub EPG

One combined, compressed XMLTV guide for MovieHub. GitHub downloads and merges upstream feeds;
the TV downloads the finished file and reads its local database.

**Guide:** `https://raw.githubusercontent.com/billyke2000s/Moviehub-epg/main/epg.xml.gz`

**Coverage:** [coverage.md](coverage.md), [coverage.json](coverage.json), [remaining gaps](unmatched.json).
These files appear only after a successful generation. They measure the public default channel lists,
not private accounts or a particular viewer's installed database. Identifier counts include aliases.

## Daily generation

The public GitHub-hosted workflow runs at **04:37 UTC daily** (04:37 UK winter / 05:37 UK summer).
Use **Actions → Generate and publish MovieHub EPG → Run workflow** for a manual refresh.
Source changes also trigger generation. Scheduled runs use the default branch. GitHub may delay or
drop scheduled jobs during high load; a cron time is not a delivery guarantee. Public-repository
scheduled workflows can be disabled after 60 days without repository activity and require re-enabling
in Actions. See [GitHub's schedule documentation](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule).

Source caches are restored from GitHub Actions cache, not from TV devices. Fresh source files replace
their cache only after parsing and source-coverage validation. Failed sources reuse cached listings
only while their original programme times remain usable. Cache eviction or a first run has no saved
source fallback. Expired listings are never shifted forward or invented. GitHub's cache quotas and
eviction rules can remove inactive caches; the last published guide remains in Git history.

The merge targets yesterday through seven days ahead, bounded by available upstream data. Explicit
UTC offsets handle daylight-saving transitions. Native provider identities and country-scoped name
aliases coexist. +1 and regional variants stay distinct; the London feed additionally answers to
the national name, matching MovieHub's existing behaviour. Higher-priority schedules win overlaps;
lower-priority sources fill complete gaps without fabricating shortened programme times.

Generation happens in staging. Malformed XML/entities, empty or expired sources, invalid timestamps,
large per-source drops and a large combined-coverage drop are rejected. A failed build never replaces
`epg.xml.gz`. Guide and reports publish in one commit; a concurrent source edit aborts publication.
Workflow concurrency serializes publishers. Failures appear in Actions and its job summary, while the
existing published freshness remains visible. No private feeds, credentials or stream URLs are published.

## Sources and priorities

The exact public URLs, priorities and attribution are in [sources.json](sources.json). The eight XMLTV
URLs MovieHub already fetched are retained as the starting point. Public Pluto XMLTV replaces its
per-channel device guide calls. A UK/CA/US/AU sports supplement and distinct country feeds address measured gaps; the original US1 URL is retained in the assessment, with US2 added because US1 returns 404. Existing public inline provider catalogues are also read on GitHub through MovieHub’s pinned audited interpreter, preserving exact native guide identities without publishing stream URLs or sessions. See [the migration inventory](docs/SOURCE_INVENTORY.md).

Source code licences do not automatically grant all rights in broadcaster schedule descriptions.
Upstream data remains attributed to its respective providers; this repository makes no new licence
claim over that data. Source metadata records the licence/permission evidence and uncertainties.
No signed-in, private, paywalled or access-controlled feed is configured; upstream refusals are reported.

## Development

Python 3.11 or newer; no database server, paid service or secret is required.

```sh
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python -m epg.build
```

Validated output is staged in `out/`; local runs never overwrite the published files automatically.
Review `out/coverage.md`, source contributions, freshness and unmatched identities before changing
source priorities or coverage thresholds. Do not add private playlists to the public inventory.
