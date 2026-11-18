# predicate-chain Phase 1 pilot report

Parser version 1.1.0. Generated 2026-11-17T01:41:34+00:00 UTC. 142 of 142 pilot devices processed; 2,745 more ancestor nodes processed in the chain walk.

**Status:** Complete. Two online passes on your PC (the second with parser 1.1.0 and the Gate 1 settings) plus an offline re-parse. All 142 pilot chains are fully walked; 2,887 nodes processed under parser 1.1.0, 0 download errors in the second pass.

## Gate 1 decisions

| # | Decision | Status |
|---|---|---|
| 1 | Stop rule "No summary on file (pre-1991)" for blank-status clearances decided 1990 or earlier | Approved and applied |
| 2 | Stop rule "No summary on file (1991-1995)" for Summary or blank status decided 1991-1995 | Approved and applied |
| 3 | `PDF_URL_STRATEGY = pattern_first` | Approved and applied |
| 4 | Review-queue strictness (see below) | Option C (assumed, applied as parser 1.2.0) |
| 5 | Hand-check of 40 devices | Done: 112 of 112 edges and 40 of 40 devices correct (section 11) |

Evidence for 1 and 2: 0 of 27 pre-1991 and 0 of 17 1991-1995 pilot devices had a Summary PDF online. Across all pilot nodes decided in 1995 or earlier, 2 of 219 had a PDF and neither listed a predicate.

**Decision 4, recommendation C:** "PMA predicate" flags become informational (they mark real PMA ancestors such as the BAK, RAY, LT-CAGE and Brantigan cages). "Mentioned, not classified" becomes informational only when the document already has a HIGH predicate from a labeled section; in a dead-end document it still sends the document to review, because there it usually means a miss. On the 2,366 parsed pilot documents this moves 124 from AMBIGUOUS to CLEAN (1,360 to 1,236). What still drives review: 537 dead ends with no numbered predicate, 427 documents with a MEDIUM or LOW edge, and 272 with predicates in more than one section. Suggested Phase 4 order: LOW edges, misread numbers and wrong files first; then the 84 dead ends that mention numbers (likely misses); then MEDIUM and multi-section documents; dead ends with no number anywhere last.

## Key findings

1. **Truncation is real for modern devices.** 13 of 142 pilot chains hit TRUNCATED at 10 generations, all from 2010 or later (K261809 among them). Among the 58 devices that cite any predicate, that is 22%. Those chains already reach 1976-1990 ancestors on other branches, so a higher limit would add depth, not an older origin.
2. **Modern chains are large.** The median chain for a device with predicates holds 30 ancestor nodes; the largest holds 1,457 (K223146) and K261809 holds 631. The Phase 5 lookup tool will need a primary-predicate view and generation filters to stay readable.
3. **OCR is required.** Every 1996-1999 summary is a scan and about half of 2020-2026 summaries are FDA eSTAR forms with no text layer. Tesseract handled all of them (0 left at "needs OCR").
4. **The URL pattern holds.** 1,676 of 1,676 detail-page links matched the first URL-pattern guess; the second pass downloaded 690 PDFs by pattern alone.
5. **Phase 2 estimate:** about 14,200 PDFs, about 3.5 GB, about 7 hours with the approved settings (about 12.3 hours with the pilot settings).
6. **Phase 3 estimate is wide.** The frontier projection moved from about 5,000 to about 10,000 extra nodes once the pilot chains were complete. Treat it as order of magnitude (roughly 6 hours at the pilot's pace for 10,000). The real count comes from Phase 2 edges and goes to you before Phase 3 starts.
7. **Parser 1.0.0 to 1.1.0** (see CHANGELOG.md): on the same nodes HIGH edges rose from 1,564 to 2,067, LOW fell from 411 to 208, and false wrong-file stops fell from 4 to 0. One wrong-file flag remains (K973119's PDF reads as K974093) and sits in the review queue.
8. **Two stop reasons were added** so that every node has exactly one: "Summary parsed, no predicate found" and "Wrong file (PDF is for another number)".

## 1. Do pre-1991 and blank-status clearances have a Summary PDF online?

| Group (pilot devices) | Devices | Summary PDF online | Predicates found | FDA detail-page link |
|---|---|---|---|---|
| 1976-1990 stratum (all blank status) | 20 | 0 | 0 | no link: 20 |
| All pilot pre-1991 blank-status seeds | 27 | 0 | 0 | no link: 27 |
| 1991-1995 blank-status seeds (any stratum) | 9 | 0 | 0 | no link: 9 |
| 1991-1995 Summary-status seeds | 8 | 0 | 0 | no link: 8 |
| 1996+ blank-status seeds (any stratum) | 6 | 5 | 1 | Summary: 5, no link: 1 |

## 2. Text extraction

| Method | Pilot devices | All pilot nodes |
|---|---|---|
| OCR | 36 | 641 |
| text layer | 43 | 1725 |

## 3. Edge confidence

| Confidence | Pilot devices' edges | All edges |
|---|---|---|
| HIGH | 164 | 5127 |
| MEDIUM | 22 | 731 |
| LOW | 29 | 578 |

## 4. Parse status by era (pilot devices)

| Era | CLEAN | AMBIGUOUS | NOT PARSED (no PDF, Statement, DEN) |
|---|---|---|---|
| 1976-1990 | 0 | 0 | 27 |
| 1991-1995 | 0 | 0 | 30 |
| 1996-1999 | 1 | 18 | 3 |
| 2000-2009 | 5 | 13 | 2 |
| 2010-2019 | 13 | 7 | 0 |
| 2020-2026 | 11 | 11 | 1 |

## 5. Stop reasons

| Stop reason | Pilot devices | All pilot nodes |
|---|---|---|
| (continues) | 58 | 1829 |
| Summary parsed, no predicate found | 9 | 344 |
| Predicate has no FDA number | 12 | 192 |
| No summary on file (1991-1995) | 17 | 150 |
| No Summary PDF available | 3 | 142 |
| No summary on file (pre-1991) | 27 | 106 |
| Statement only, no predicate data | 15 | 92 |
| K-number not found in any FDA source | 0 | 18 |
| PMA (P number) | 0 | 12 |
| Wrong file (PDF is for another number) | 0 | 1 |
| De Novo (DEN) | 1 | 1 |

## 6. Downloads

- PDFs downloaded or cached: 2,366. Average 0.249 MB, median 0.17 MB.
- Average download time: 0.99 s per PDF (requests are throttled to one per second).
- URL pattern check: 1,676 of 1,676 detail-page links equal the first URL-pattern guess; 690 PDFs came from the pattern fallback.

| Per node (your PC) | Nodes | Median s | Mean s |
|---|---|---|---|
| downloaded, OCR | 645 | 4.45 | 4.79 |
| looked up, no PDF | 345 | 1.97 | 1.79 |
| no request (Statement, DEN, PMA) | 171 | 0.0 | 0.06 |
| downloaded, text layer | 1765 | 1.89 | 1.69 |
| all | 2926 | 1.97 | 2.29 |

## 7. Full-run extrapolation (18,224 starting-set clearances)

| Group | Clearances | Pilot sample | PDF online rate | OCR share | Hours (A) | Hours (B) |
|---|---|---|---|---|---|---|
| pre1991_blank | 1781 | 27 | 0.0 | 0.0 | 0.97 | 0.02 |
| 1991-1995 | 991 | 17 | 0.0 | 0.0 | 0.54 | 0.01 |
| 1996-1999 | 1263 | 21 | 0.9 | 1.0 | 1.48 | 1.16 |
| 2000-2009 | 4231 | 19 | 0.95 | 0.06 | 2.38 | 1.27 |
| 2010-2019 | 5532 | 20 | 1.0 | 0.2 | 3.69 | 2.15 |
| 2020-2026 | 3521 | 22 | 1.0 | 0.55 | 3.21 | 2.24 |

- Statement-only and De Novo clearances need no request: 905.
- Expected Summary PDFs: about 14,204, about 3.54 GB of cache.
- Runtime A (pilot settings: detail page first, pre-1991 blanks looked up): about 12.3 hours.
- Runtime B (approved Gate 1 settings: URL pattern first, 1995-and-earlier clearances stopped without a request): about 6.9 hours.
- The ancestor frontier (Phase 3) comes on top of this.

## 8. Chains

- Pilot chains that hit TRUNCATED at MAX_GENERATIONS: **13** of 142.
- Chains fully extracted within the pilot: 142 of 142.

| Chain depth (generations) | Pilot devices |
|---|---|
| 0 | 84 |
| 1 | 11 |
| 2 | 11 |
| 3 | 3 |
| 4 | 2 |
| 6 | 3 |
| 7 | 7 |
| 8 | 4 |
| 9 | 2 |
| 10 | 15 |

- Ancestors outside the starting set reached by the pilot: 294.
- Rough frontier projection for the full run: about 10,095 extra nodes (species-accumulation fit, exponent 0.72). Order of magnitude only; Phase 2 edges give the real count before Phase 3 starts.

## 9. Flags and review queue

| Flag | Count (all pilot nodes) |
|---|---|
| mentioned, not classified | 955 |
| partial name match | 377 |
| name mismatch | 346 |
| PMA predicate | 150 |
| probable misread number | 18 |
| wrong file | 1 |

| Review queue item | Count |
|---|---|
| AMBIGUOUS document | 1360 |
| LOW confidence edge | 578 |
| probable misread number | 18 |
| wrong file | 1 |

## 10. Hand-check workbook

`outputs/Pilot_HandCheck_2026-11-16.xlsx`: 40 pilot devices (18 CLEAN, 22 AMBIGUOUS, 1996-2026) with page numbers, extracted predicates and blank Y/N columns. The pilot devices did not change in the second pass, so the workbook is current.

## 11. Hand-check results (human review, 2026-11-16)

Asher Breverman checked all 40 hand-check devices against their Summary PDFs.

| Measure | Correct | Checked | 95% Wilson interval |
|---|---|---|---|
| Edge: number correct | 112 | 112 | 96.7% to 100% |
| Edge: role (primary/reference) correct | 112 | 112 | 96.7% to 100% |
| Edge: really a predicate | 112 | 112 | 96.7% to 100% |
| Device: all predicates found | 40 | 40 | 91.2% to 100% |
| CLEAN devices, all found | 18 | 18 | 82.4% to 100% |
| AMBIGUOUS devices, all found | 22 | 22 | 85.1% to 100% |

The 112 edges exclude 3 devices with no predicate in the PDF and 7 "no FDA number" rows. Those 10 devices were confirmed under "all predicates found".

What this supports: on 1996-2026 summaries with a readable PDF, parser 1.1.0 made no error the reviewer found. That includes OCR'd scans, eSTAR forms, family members and reference devices.

What it does not support: an error rate of zero. With 112 edges, the data are still consistent with an edge error rate up to about 3.3%, and up to about 9% of devices with a missed predicate. AMBIGUOUS documents were as accurate as CLEAN ones here, so AMBIGUOUS means "unverified", not "wrong". The workbook showed the parser's answer next to each PDF, which can anchor a reviewer toward agreeing. Phase 6 draws a fresh, independent sample of 40.

## Limitations

- Predicates are what the submitter wrote in the Summary. The tool does not verify FDA's internal review.
- Substantial equivalence is a regulatory finding. It says nothing about clinical performance, outcomes, or price.
- 510(k) summaries were not required before 1990, so most chains end in the early 1990s whatever the generation limit. Statement-only clearances and unreadable PDFs also end a branch.
- The starting set is orthopedic product codes only (FDA Orthopedic panel and 21 CFR 888). Non-orthopedic ancestors are covered through the frontier.
- Applicant names appear as printed at clearance and are not rolled up to current owners.
- Text extraction can misread layouts. The Flags tab and Reviewer_Checklist exist for human review.
- Segment labels are unofficial (assigned by Claude, not FDA).
- Independent research tool built from public FDA data, provided as is, not regulatory advice, and the author's personal work and views.
