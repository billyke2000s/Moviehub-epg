# Migration from MovieHub Experimental exp-10

Audited source: MovieHub `b29971ab9f244189de00265d614772eed6f896e4`.

| Existing device path | Existing URLs/behaviour | Migration |
| --- | --- | --- |
| `EpgImporter` | Freeview XML, Sky London HD XML, epgshare01 UK1, IE1 and US1 gzip | All five exact URLs are configured server-side, priorities 10 / 20 / 30. |
| `ProviderGuide.PLEX` | i.mjh.nz/Plex/gb.xml.gz and us.xml.gz | Both exact URLs; provider ids use the stable component after the last dash. |
| `ProviderGuide.SAMSUNG` | i.mjh.nz/SamsungTVPlus/gb.xml.gz | Exact URL; Samsung ids stay unchanged, including case. |
| `NativeSources.guide` | Anonymous Pluto boot session, then `PlutoSource.guide` per 20 catalogue channels | Public i.mjh.nz/PlutoTV/gb.xml.gz and us.xml.gz replace separate device guide requests. More regions require verified coverage/configuration; regions not configured remain explicit gaps. |
| `AdapterSources.guide` | Inline programmes in provider catalogue responses | No separate XMLTV URL. Device programme writes are retired; incidental fields in channel catalogues are not treated as an extra EPG. Providers lacking a public matching guide are reported as gaps. |
| `EngineSources.guide` | FreeLiveSports inline catalogue programmes | No standalone guide URL. The client no longer imports inline schedules alongside the combined guide. |
| Free-TV playlist header | Many `x-tvg-url` references | MovieHub's `Playlist` reader did not fetch these header URLs. They are referenced metadata, not approximately twenty executed XMLTV download paths. No blanket import of every redundant feed. |
| Private account EPG | No separate user-configured XMLTV importer found in this build | M3U/Xtream credentials and channel imports remain device-local; no private URLs are sent to this repository. |

`sources.json` is the complete executable URL inventory. This repository was empty when inspected,
so there were no obsolete files, public guide URLs or Git history to remove. Git history is retained.

## Mapping and source selection

`epg/identity.py` ports MovieHub's quality/country stripping, UKTV aliases, London national aliases,
GB/UK equivalence and the Gold Radio/Gold TV distinction. Explicit aliases also cover BBC1/BBC2 and
the common `SkySportsPremiereLeague` spelling. Country prefixes are never used to borrow another
country's schedule. Provider-native ids publish independently of generic name keys and retain priority
in MovieHub. Numeric guide-id aliases are retained for playlists already using those tvg-ids.

Public default Free-TV and iptv-org lists are used as the assessed inventory. Only channel names,
public tvg-ids and countries are retained: stream URLs are discarded. This cannot establish coverage
of private accounts or every optional provider installed on a specific TV. `unmatched.json` reports
remaining assessed gaps without hiding unsupported countries.

## Additional source assessment

- `farleyflex/epg-guide` explicitly publishes a client XMLTV covering UK sports plus CA/US/AU. A live
  inspection found 75 channels and 8,478 programmes through 29 October 2026. Its lower priority avoids
  replacing working original-source schedules; source contribution reports measure the actual gain.
- iptv-org's current `GUIDES.md` listed no healthy hosted guides (all listed hosts had zero channels)
  when inspected. The utility repository itself is not a ready-to-download current global guide.
- epgshare01 `ALL_SOURCES1` and every playlist-header feed are not downloaded by default: they duplicate
  configured feeds and can be very large. New countries are added after measuring country-specific gaps,
  not by downloading dozens of redundant feeds to every TV.
- Freeview's GPL-3.0 project offers XMLTV for personal use; Sky's generator is Unlicense and its own
  README describes its backend as unsupported. i.mjh.nz, epgshare01 and the supplement have no blanket
  broadcaster-data redistribution licence verified here. Attribution and uncertainty are recorded;
  public availability is not represented as a licence over all upstream programme descriptions.
