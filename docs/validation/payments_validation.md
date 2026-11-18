# Open Payments build: validation report

Data: CMS Open Payments program years 2019 to 2025 (published June 30, 2026), GUDID full release November 2026.

## 1. Reproducing the Sep 21, 2026 article base (2025 general payments)

The article filtered to MD, DO and DPM recipients with an orthopedic specialty in any of six taxonomy slots. Without the original script, three readings of that filter are compared with the published figures.

| Filter | Payments | Dollars | Companies (payer IDs) | Recipients |
| --- | --- | --- | --- | --- |
| Published | 661,667 | $727,535,622 | 1,007 | 47,816 |
| A: MD/DO orthopaedic + all DPM | 547,472 (-17.3%) | $627,227,086 (-13.8%) | 843 | 39,204 (-18.0%) |
| B: A + neurosurgery | 637,391 (-3.7%) | $721,321,977 (-0.9%) | 941 | 44,928 (-6.0%) |
| C: B + hand surgery + sports medicine | 643,570 (-2.7%) | $725,433,448 (-0.3%) | 943 | 46,312 (-3.1%) |

Rows for recipients outside orthopedics, neurosurgery, podiatry and hand surgery were only loaded from orthopedic payers, so a broader filter cannot be tested exactly here.

Nature of payment under the closest filter (C: B + hand surgery + sports medicine):

| Nature | Published payments | Here | Published $M | Here $M |
| --- | --- | --- | --- | --- |
| Royalty or License | 13,261 | 13,223 (-0.3%) | 421.9 | 421.8 |
| Consulting Fee | 31,300 | 31,014 (-0.9%) | 132.1 | 131.6 |
| Acquisitions | 132 | 132 (+0.0%) | 40.8 | 40.8 |
| Compensation for services other than consulting | 6,613 | 6,436 (-2.7%) | 37.2 | 36.7 |
| Travel and Lodging | 96,891 | 96,294 (-0.6%) | 35.8 | 35.6 |
| Food and Beverage | 504,214 | 487,353 (-3.3%) | 27.6 | 27.1 |
| Education | 5,224 | 5,184 (-0.8%) | 11.4 | 11.4 |
| Grant | 973 | 973 (+0.0%) | 7.8 | 7.8 |
| Debt forgiveness | 553 | 549 (-0.7%) | 7.8 | 7.7 |
| Compensation for serving as faculty | 1,110 | 1,094 (-1.4%) | 2.6 | 2.5 |
| Honoraria | 436 | 424 (-2.8%) | 2.0 | 2.0 |

## 2. Named reporting entities (2025, closest filter)

| Entity | Published recipients | Here | Published $ | Here $ |
| --- | --- | --- | --- | --- |
| DePuy Synthes Products, Inc. | 264 | 264 (+0.0%) | $61,463,424 | $61,463,381 (-0.0%) |
| DePuy Synthes Sales Inc. | 9,581 | 9,582 (+0.0%) | $1,877,876 | $1,882,783 (+0.3%) |
| Stryker Corporation | 19,180 | 19,162 (-0.1%) | $102,600,000 | $102,197,057 (-0.4%) |
| Arthrex, Inc. | 4,267 | 4,263 (-0.1%) | $102,100,000 | $102,470,269 (+0.4%) |

## 3. What the orthopedic product filter removes (same entities, same recipients)

| Entity | All payments | Orthopedic scope | Removed |
| --- | --- | --- | --- |
| DePuy Synthes Products, Inc. | $61,463,381 | $60,159,306 | -2.1% |
| DePuy Synthes Sales Inc. | $1,882,783 | $1,587,131 | -15.7% |
| Stryker Corporation | $102,197,057 | $95,439,118 | -6.6% |
| Arthrex, Inc. | $102,470,269 | $102,010,156 | -0.4% |

Diversified vendors (under 80% of matched device tags orthopedic); for these, payments count only when they name an orthopedic product or go untagged to an orthopedic, neurosurgery or podiatry recipient:

- Medtronic: 142,835 of 1,415,558 tags orthopedic (10%)
- Stryker: 706,826 of 960,521 tags orthopedic (74%)
- Smith+Nephew: 223,038 of 502,722 tags orthopedic (44%)
- DePuy Synthes (Johnson & Johnson): 224,294 of 372,597 tags orthopedic (60%)
- Integra LifeSciences: 64 of 353,717 tags orthopedic (0%)
- Zimmer Biomet: 145,649 of 206,193 tags orthopedic (71%)
- Highridge Medical: 8,883 of 145,747 tags orthopedic (6%)
- Globus Medical: 75,067 of 108,423 tags orthopedic (69%)
- NuVasive: 50,710 of 65,744 tags orthopedic (77%)
- Bioventus: 29,664 of 57,396 tags orthopedic (52%)
- Enovis (DJO): 38,463 of 50,320 tags orthopedic (76%)
- Ethicon (Johnson & Johnson): 108 of 13,483 tags orthopedic (1%)
- Medline Industries LP: 8,145 of 10,711 tags orthopedic (76%)
- Intrinsic Therapeutics: 0 of 9,370 tags orthopedic (0%)
- Karl Storz: 44 of 5,463 tags orthopedic (1%)

## 4. Internal consistency

- agg_vendor_year (pit) adds back to pay_fact: yes ($4,652,673,098, 2,874,203 payments)
- agg_vendor_profile all-years (pit) adds back: yes
- agg_vendor_year (current) adds back to pay_fact: yes ($4,652,673,098, 2,874,203 payments)
- agg_vendor_profile all-years (current) adds back: yes
- No NPI or name columns in aggregate tables: yes

## 5. Roll-up by date

- NuVasive payments in 2022 counted under NuVasive (as owned at the time): $16,189,680
- NuVasive payments in 2023 counted under Globus Medical (as owned at the time): $4,412,967
- NuVasive payments in 2023 counted under NuVasive (as owned at the time): $13,708,214

## 6. Product links

- 2025 orthopedic-scope dollars naming an orthopedic product: $464,680,934 of $666,845,630 (70%)

Top 2025 products by dollars naming them (a payment counts for each product it names):

| 510(k) | Brand | Tier | Dollars | Payments |
| --- | --- | --- | --- | --- |
| K140881 | ATTUNE | 1 | $32,477,427 | 2,093 |
| K220930 | Mako | 1 | $20,966,049 | 31,756 |
| K150307 | Mako | 1 | $20,966,049 | 31,756 |
| K242831 | Mako | 1 | $20,966,049 | 31,756 |
| K150410 | Mako | 1 | $20,946,680 | 31,730 |
| K032578 | CD HORIZON® Spinal System | 1 | $20,220,609 | 5,313 |
| K153603 | Invictus | 2 | $14,373,527 | 537 |
| K214006 | Invictus | 2 | $12,128,603 | 537 |
| K221926 | Invictus | 2 | $12,128,603 | 537 |
| K232275 | Invictus | 2 | $12,128,603 | 537 |
| K192938 | Invictus | 2 | $12,128,603 | 537 |
| K241519 | Invictus | 2 | $12,128,603 | 537 |
| K181677 | Invictus | 2 | $12,128,603 | 537 |
| K213460 | Invictus | 2 | $12,128,603 | 537 |
| K203056 | Invictus | 2 | $12,128,603 | 537 |

## 7. Spot-check on the CMS Open Payments website

Search each company at openpaymentsdata.cms.gov and compare its 2025 general payments total (all recipients).

| Paying entity | 2025 general payments here | Payments |
| --- | --- | --- |
| Arthrex, Inc. | $106,092,053 | 46,235 |
| Globus Medical, Inc. | $36,057,394 | 55,935 |
| TREACE MEDICAL CONCEPTS, INC. | $12,017,157 | 18,333 |

## 8. Totals

- 2019: $704,347,596 in 474,018 payments from 208 vendors (orthopedic scope, listed vendors)
- 2020: $568,500,763 in 232,648 payments from 211 vendors (orthopedic scope, listed vendors)
- 2021: $620,187,366 in 343,793 payments from 209 vendors (orthopedic scope, listed vendors)
- 2022: $726,238,341 in 410,681 payments from 222 vendors (orthopedic scope, listed vendors)
- 2023: $685,877,460 in 436,714 payments from 227 vendors (orthopedic scope, listed vendors)
- 2024: $680,675,942 in 475,254 payments from 225 vendors (orthopedic scope, listed vendors)
- 2025: $666,845,630 in 501,095 payments from 208 vendors (orthopedic scope, listed vendors)
