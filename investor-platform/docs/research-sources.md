# Research manager sources

Verified on 2026-10-07. The seed contains 21 research managers. Technology and growth managers come first; the focus labels are research categories, not a measured technology exposure or an endorsement. People are associated founders or investors, not a claim that they currently control every reported position. The SEC submission indexes verify each reporting entity and its CIK. ([SEC submissions API](https://www.sec.gov/search-filings/edgar-application-programming-interfaces))

`history_start_year` is the report year of the earliest 13F-HR found in the checked submission indexes, including historical shards where present. It is not the firm's founding year and does not prove uninterrupted quarterly filings. Establish ten-year coverage from imported filings and report missing quarters. D1 starts at 2018-12-31 and GQG at 2016-12-31: neither has ten years of observed periods as of verification. Pershing's current parent starts at 2025-06-30; its legacy filer starts at 2005-12-31. Keep the entities distinct. ([SEC D1](https://data.sec.gov/submissions/CIK0001747057.json); [SEC GQG](https://data.sec.gov/submissions/CIK0001697233.json); [SEC current Pershing](https://data.sec.gov/submissions/CIK0002026053.json); [SEC legacy Pershing](https://data.sec.gov/submissions/CIK0001336528.json))

## Earliest observed holdings report

| Manager | CIK | Reporting period | Filed | Evidence |
| --- | --- | --- | --- | --- |
| Tiger Global | 0001167483 | 2001-12-31 | 2002-02-14 | [SEC index](https://data.sec.gov/submissions/CIK0001167483.json) |
| Coatue | 0001135730 | 2000-12-31 | 2001-03-02 | [SEC index](https://data.sec.gov/submissions/CIK0001135730.json) |
| Viking Global | 0001103804 | 1999-12-31 | 2000-02-14 | [SEC index](https://data.sec.gov/submissions/CIK0001103804.json) |
| Lone Pine Capital | 0001061165 | 2004-12-31 | 2005-02-14 | [SEC index](https://data.sec.gov/submissions/CIK0001061165.json) |
| Altimeter | 0001541617 | 2011-12-31 | 2012-02-14 | [SEC index](https://data.sec.gov/submissions/CIK0001541617.json) |
| Dragoneer | 0001602189 | 2014-12-31 | 2015-02-17 | [SEC index](https://data.sec.gov/submissions/CIK0001602189.json) |
| Whale Rock | 0001387322 | 2006-12-31 | 2007-02-13 | [SEC index](https://data.sec.gov/submissions/CIK0001387322.json) |
| SCGE Management | 0001537530 | 2011-12-31 | 2012-02-14 | [SEC index](https://data.sec.gov/submissions/CIK0001537530.json) |
| Sands Capital | 0001020066 | 1999-03-31 | 1999-05-06 | [SEC index](https://data.sec.gov/submissions/CIK0001020066.json) |
| WCM Investment Management | 0001061186 | 1999-04-30 | 1999-05-06 | [SEC index](https://data.sec.gov/submissions/CIK0001061186.json) |
| Polen Capital | 0001034524 | 1999-03-31 | 1999-04-23 | [SEC index](https://data.sec.gov/submissions/CIK0001034524.json) |
| Fundsmith | 0001569205 | 2012-12-31 | 2013-02-13 | [SEC index](https://data.sec.gov/submissions/CIK0001569205.json) |
| Akre Capital | 0001112520 | 2000-12-31 | 2001-08-09 | [SEC index](https://data.sec.gov/submissions/CIK0001112520.json) |
| Baillie Gifford | 0001088875 | 1999-03-31 | 1999-06-18 | [SEC index](https://data.sec.gov/submissions/CIK0001088875-submissions-001.json) |
| Berkshire Hathaway | 0001067983 | 1999-03-31 | 1999-05-17 | [SEC index](https://data.sec.gov/submissions/CIK0001067983-submissions-001.json) |
| Pershing Square | 0002026053 | 2025-06-30 | 2025-08-14 | [SEC index](https://data.sec.gov/submissions/CIK0002026053.json) |
| Third Point | 0001040273 | 1999-06-30 | 1999-11-26 | [SEC index](https://data.sec.gov/submissions/CIK0001040273.json) |
| TCI Fund Management | 0001647251 | 2015-06-30 | 2015-08-17 | [SEC index](https://data.sec.gov/submissions/CIK0001647251.json) |
| Greenhaven Associates | 0000846222 | 1999-03-31 | 1999-05-04 | [SEC index](https://data.sec.gov/submissions/CIK0000846222.json) |
| D1 Capital Partners | 0001747057 | 2018-12-31 | 2019-02-14 | [SEC index](https://data.sec.gov/submissions/CIK0001747057.json) |
| GQG Partners | 0001697233 | 2016-12-31 | 2017-02-14 | [SEC index](https://data.sec.gov/submissions/CIK0001697233.json) |

## Letter sources

- [Berkshire shareholder letters](https://www.berkshirehathaway.com/letters/letters.html): public archive.
- [Fundsmith documents](https://www.fundsmith.co.uk/documents): annual and semiannual letters, alongside fund documents.
- [Pershing 2017 annual letter](https://assets.pershingsquareholdings.com/2022/10/07155606/2017-Annual-Report-Letter-Only.pdf): verified historical letter from Pershing Square Holdings. Its old archive route was inaccessible at verification, so the seed links to a document, not an unverified archive.
- [Third Point Q1 2025 letter](https://assets.thirdpoint.com/f/160155/x/9bcf34e846/third-point-q1-2025-investor-letter.pdf): verified letter on the manager's asset domain. Its former listed-fund domain now [redirects to Malibu Life](https://www.malibulifeinsurance.com/); do not use it as a current investor-letter archive.
- Null letter links mean no public source was verified. They do not imply that a manager never publishes letters. Login-only investor portals are not public letter archives.

## Reading quarterly changes

Form 13F gives delayed holdings snapshots, not a transaction ledger. It omits short positions and many assets. Share changes can result from trades, splits, reorganizations or reporting changes; motive and trade prices are unknown unless a manager explains them. A decade of disclosed holdings is useful research history but does not establish investment skill or trust. ([SEC Form 13F FAQ](https://www.sec.gov/rules-regulations/staff-guidance/division-investment-management-frequently-asked-questions/frequently-asked-questions-about-form-13f))

Pershing's legacy manager directs readers to its parent's holdings report. Track that change before classifying a missing holding as an exit. ([Legacy notice](https://www.sec.gov/Archives/edgar/data/1336528/000117266126003777/primary_doc.xml); [parent report](https://www.sec.gov/Archives/edgar/data/2026053/000117266126003790/0001172661-26-003790-index.html))

## References

### SEC filings and data

- The manager table links to the submission index used for each CIK and first observed report. The seed also retains a filing-index link for each report.
- [SEC submissions API](https://www.sec.gov/search-filings/edgar-application-programming-interfaces): entity metadata, filing indexes and historical shards.
- [SEC Form 13F FAQ](https://www.sec.gov/rules-regulations/staff-guidance/division-investment-management-frequently-asked-questions/frequently-asked-questions-about-form-13f): reporting scope and timing.
- [Pershing legacy notice](https://www.sec.gov/Archives/edgar/data/1336528/000117266126003777/primary_doc.xml) and [parent report](https://www.sec.gov/Archives/edgar/data/2026053/000117266126003790/0001172661-26-003790-index.html): reporter transition.

### Manager websites and letters

- The seed's `website_url`, `letters_url` and `source_urls` retain verified public destinations. The letter sources above identify whether each destination is an archive or a single document.
