# Additional guide assessment — 25 October 2026

This assessment starts from the generated unmatched-channel report, not upstream headline channel totals. Probe matches are candidates, not promises about the viewer's private/device inventory. Actual publication is measured in the generated coverage report.

## Incorporated sources

| Source | Reviewed use |
| --- | --- |
| BuddyChewChew Xumo XMLTV | Exact `enginexumo:<numeric id>` mapping; 436 formerly unmatched native ids also appear in this guide. Generic names remain US-scoped and below native/established guide priorities. |
| EPGShare CA2 | Working Canadian replacement supplement; CA1 returns 404. Keep city/regional identifiers distinct. |
| EPGShare NL1, PL1, TR1 | Country-scoped Netherlands, Polish and Turkish coverage, with direct current matches in the unmatched inventory. |
| EPGTalk UK | Explicit reviewed keys only: ATN Bangla, Faith, Foodxp and Latest TV. No technical identifiers, numbered display-name aliases or unrelated-country entries are published. |
| EPGTalk US | Fifteen reviewed exact national/explicit East-feed keys. East and West stay separate. Ambiguous CTV/Discovery Turbo matches were excluded. |

All remain lower priority than established native/Freeview/Sky sources where identities conflict. Source URLs, project attribution, limitations and rights evidence are recorded in `sources.json`. Public availability is not represented as a blanket broadcaster-data redistribution licence. No stream URLs or private playlists are processed for these additions.

## Exclusions

- Fourteen GlobeTV UK/US/Russia files downloaded and parsed successfully but contained expired listings, ending in September 2025–January 2026. They add no current coverage despite an upstream daily-update description.
- EPGTalk US-local supplied only one candidate missing identity (MeTV), already supplied by the selected US supplement; not added redundantly.
- EPGTalk FreeTV has mixed provider/country labels without verified MovieHub-native identities. Name-only cross-country guessing is not used.
- EPGShare MX1 added just three candidate missing identities in this pass; omitted to favour the larger gains above.
- MBC from the UK-labelled supplemental file was too ambiguous to assert identity; omitted.

## Mapping and validation

`only_keys` limits selected supplements to reviewed canonical identities. The national `Channel4.uk@UK` playlist variant receives an explicit UK-only alias, without relaxing `@Scotland`, other regional qualifiers or time-shift separation. Regression tests cover source filtering and native Xumo ids. Existing malformed/stale-source recovery, original timestamp expiry, last-guide retention and compressed-size validation remain in force.

The TV still loads one finished guide at the same URL. These are server-side changes; experimental exp-11 does not need another APK build.
