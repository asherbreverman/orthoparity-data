# predicate-chain accuracy report (Phase 6)

Written 2026-11-17. Parser 1.3.1, review rule D, Phase 4 review decisions applied. Source: `Validation_HandCheck_2026-11-17.xlsx`, a fresh random sample of 40 orthopedic clearances (10 per era, 1996 to 2026) drawn with a fixed seed from devices whose Summary PDF was read, excluding every pilot device. Asher Breverman checked each reported predicate against the PDF.

## Results

- **Edge error rate:** 0 of 143 (0.0%); 95% Wilson interval 0.0% to 2.6%. An edge counts as an error if the number is wrong or it is not a predicate under rule D.
- **Role errors (primary vs reference):** 0 of 143 (0.0%); 95% interval 0.0% to 2.6%. Reported separately; a role error does not change which devices are in a chain.
- **Device error rate:** 0 of 38 (0.0%); 95% interval 0.0% to 9.2%. A device counts as an error if any reported predicate is wrong or the tool missed a numbered predicate.
- Devices where the tool missed at least one numbered predicate: 0 of 38.

### Edges by confidence tier

| Confidence | Errors | 95% CI for the error rate |
|---|---|---|
| HIGH | 0 of 131 (0.0%) | 0.0% to 2.8% |
| LOW | 0 of 1 (0.0%) | 0.0% to 79.3% |
| MEDIUM | 0 of 11 (0.0%) | 0.0% to 25.9% |

### Edges by era

| Era | Errors | 95% CI for the error rate |
|---|---|---|
| 1996-1999 | 0 of 33 (0.0%) | 0.0% to 10.4% |
| 2000-2009 | 0 of 26 (0.0%) | 0.0% to 12.9% |
| 2010-2019 | 0 of 50 (0.0%) | 0.0% to 7.1% |
| 2020-2026 | 0 of 34 (0.0%) | 0.0% to 10.2% |

### Devices by era

| Era | Errors | 95% CI for the error rate |
|---|---|---|
| 1996-1999 | 0 of 8 (0.0%) | 0.0% to 32.4% |
| 2000-2009 | 0 of 10 (0.0%) | 0.0% to 27.8% |
| 2010-2019 | 0 of 10 (0.0%) | 0.0% to 27.8% |
| 2020-2026 | 0 of 10 (0.0%) | 0.0% to 27.8% |

## What this sample can and cannot support

- This is a small sample: 38 devices and 143 edges. The intervals above are wide, and the per-tier and per-era rows rest on even fewer cases. Read them as rough ranges, not precise rates.
- Zero errors in a group does not mean the tool is error-free there. With n checks and no errors, the upper end of the 95% interval is roughly 3.7/n (for example about 9% at n = 40).
- The sample covers 1996 to 2026, the years with posted summaries. Earlier chains end by rule (no summary on file), so there is nothing to extract or check for them.
- The check measures extraction against the document. It does not test whether FDA agreed with the submitter's choice of predicate, or anything about clinical performance, outcomes or price.
- Rule D counts every K-number in a Summary as a predicate; this report judges the tool against that rule, not against a narrower definition of 'predicate'.

## Notes on the sample

- Eight sampled devices have no K-number in their Summary (six from 1996 to 1999 and two from 2004; the tool reported none). The reviewer skipped them as old summaries without a 510(k) number; they are recorded as correct at the device level because the tool correctly reported no numbered predicate.
- Two devices (K972219, K982585) have every reported predicate checked but no answer on whether any were missed, so they are left out of the device-level count. Their 14 edges are included in the edge counts.
- 131 of the 143 sampled edges are HIGH confidence, so the MEDIUM (11) and LOW (1) rows say very little.
- Errors are not spread evenly. They concentrate in the documents the parser flags: in the Phase 4 review of the 150 highest-traffic flagged documents, about half of the flagged numbers were wrong and were corrected or removed. A random sample rarely lands on those documents. The 311 flagged documents still unreviewed (about 5% of lookup exposure) carry a higher error risk than this report shows; every output labels their edges as unreviewed.
- Earlier evidence: the Phase 1 pilot hand-check (parser 1.1.0, rule C) found 0 errors in 112 edges and 0 in 40 devices.
