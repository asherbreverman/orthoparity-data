# Limitations

Read these before relying on any number from OrthoParity. The website links to them from every page. Naming what
the data can't support is part of the method.

## Predicate chains (FDA 510(k))

- **Predicates are what the submitter wrote** in the 510(k) Summary. The tool does not see FDA's internal review
  and does not check whether FDA agreed with each predicate.
- **Substantial equivalence is a regulatory finding.** It says nothing about clinical performance, outcomes or
  price.
- **Most chains end in the early 1990s.** Summaries were not required before 1990, and none of the 1991-1995
  clearances checked in the pilot had one online. Statement-only clearances and unreadable PDFs also end a branch.
- **A dead end is where the public record stops.** It says nothing about whether that device is the true
  original of its lineage, and the tool never labels one "root" or "original".
- **Review rule D counts every K-number in a Summary as a predicate**, including numbers cited only for
  compatibility or test comparisons. A typo in a submitter's own K-number is taken at face value.
- **Reading PDFs can go wrong.** Scanned pages go through OCR; misreads are flagged and some were reviewed.
  The 40-device validation found 0 errors in 143 links, but the 95% interval runs to 2.6% per link and 9.2% per
  device.
- **The starting set covers orthopedic product codes only.** Non-orthopedic ancestors come in through the
  ancestor walk, and their own predicates are read the same way.
- **Applicant names appear as printed at clearance.** For "Is it new?", two applicants count as the same company
  when their cleaned names match, or when both belong to vendors with the same owner on the clearance date. An
  applicant name that isn't in the vendor registry (common for older, non-orthopedic ancestors) is matched by name
  only, so some line extensions can still read as competitive entries.

## Vendors and ownership

- **The vendor registry groups names by rule and by review.** A curated pattern, device and 510(k) evidence, or
  the cleaned name decides which vendor a name belongs to. Unreviewed groupings can be wrong; the registry
  workbook in `reviews/` shows each one and its basis.
- **OrthoParity benchmarks the parent company.** A parent's clearances, payments and recalls include every company
  it owns today, for all years, including years before the purchase. That answers "what does this company sell
  now", not "what did it do on its own".
- **Ownership comes from 83 dated links and 5 product-line sales, each with a source.** Deals not in
  `reference/` are not reflected. Sources include business and trade press, not only company filings, and
  `reference/ownership_sources.csv` shows the source for each claim. A few deals have only a year or month in their
  source, so their date is left blank.
- **Product-line sales move only the product codes a source names.** Where no source says which clearances went
  with a sale, they stay with the seller: Vilex in Tennessee clearances stay with OrthoPediatrics, ROSA Spine
  clearances stay with Zimmer Biomet, and EBI bone void fillers stay with Zimmer Biomet.
- **Private-equity owners are noted, not used as parents.** The roll-up stops at the operating company.
- **Listed vendors** are companies with at least one orthopedic 510(k) in the data.

## Industry payments (CMS Open Payments)

- **Open Payments reflects reported payments only.** Companies report; CMS publishes. Errors and late
  corrections in the source carry through. Records CMS lists as removed or deleted are taken out.
- **A payment is not evidence of influence, wrongdoing or product quality.** Royalties often pay for a surgeon's
  role in designing a device. Treat payments as context for a conversation, never as a judgment.
- **Orthopedic scope is a rule, not a fact.** For diversified companies (for example Medtronic or Johnson &
  Johnson) a payment counts when it names an orthopedic product, or names no product and goes to an orthopedic,
  neurosurgery or podiatry recipient. Some orthopedic spend may be missed and some non-orthopedic spend included.
- **Product links are partial.** A payment links to a 510(k) only when its device ID is in GUDID (tier 1) or its
  product name matches one of the same company's GUDID brands (tier 2). A payment that names several products
  counts in full for each, so product totals overlap and don't add up to the company total.
- **Surgeons are anonymous.** Counts of recipients use a salted hash of the NPI or CMS profile ID. The site never
  shows who was paid.
- **Teaching hospital payments** are counted in company totals but not in surgeon relationship counts.

## Catalog size (GUDID)

- **Device IDs are catalog items as labeled,** not units sold. A device's labels may cite a later or earlier
  510(k) than the one shown, so some clearances show no GUDID items.
- **The brand shown for a 510(k)** is the most common GUDID brand among its device IDs; ties go to the first
  alphabetically.

## Recalls (openFDA)

- **Recalls come from openFDA as published, 2002 to the download date.** Older recalls have no FDA class in
  openFDA and show "NOT FOUND".
- **Vendor links are by 510(k) number first,** then by the recalling firm's name (curated name patterns, then an
  exact match after removing punctuation and company suffixes). 141 recalled products matched
  no vendor and keep a blank vendor.
- **A recall is a fact about a product and a date,** not a measure of a company's overall quality. Recall rates
  depend on reporting practice and portfolio size.

## Adverse event reports (MAUDE)

- **A report is not proof that a device caused an event.** It records what a manufacturer, hospital, clinician or
  patient told FDA.
- **Counts are not rates.** FDA publishes no count of devices implanted, so widely used products have more reports.
- **A report counts only when it names the 510(k) number.** Reports with a missing or wrong number don't match,
  so product and company counts are a floor. The 649,641 matched reports equal about 48% of the 1,341,166 reports
  filed under the 254 orthopedic product codes through Nov 11, 2026; the rest name no number, a PMA, or a number
  outside the starting set.
- **Reporting practices differ by company,** and lawsuits or recalls can bring a wave of reports in a short time.
- **Most orthopedic injury reports describe a revision or another operation.**
- **A product with no matched reports shows no MAUDE section.** That means no report named its 510(k) number, not
  that nothing happened.

## Manufacturing sites, inspections and warning letters

- **Sites are current registrations only.** A site that closed or stopped making a product drops out, and its
  older inspections and warning letters drop out with it.
- **A site links to a company only through 510(k) numbers in its listings.** 11,661 of 18,224 starting-set
  clearances have at least one site link. Older clearances and products listed without a number have none, so site
  counts are a floor.
- **Company and partner sites come from name matching.** A site whose owner's name matches no company name shows as
  a partner. A rename that no source records can put a company's own site in the partner list.
- **Inspection data is not complete.** FDA's dashboard leaves out state inspections, pre-approval inspections and
  inspections still waiting for a final action, and covers fiscal year 2009 on. Foreign sites are inspected less
  often than US sites.
- **A classification describes one visit to one site.** NAI, VAI and OAI are FDA's findings for that inspection,
  not a rating of a company or its products. Partner site results describe the partner firm's own site.
- **The page shows facts, not a score.** Nothing combines recalls, reports, inspections and warning letters into a
  grade.

## Medicare add-on payments (NTAP and device pass-through)

- **The list is human-reviewed.** CMS names technologies, not 510(k) numbers. OrthoParity maps each orthopedic
  technology to its FDA records by hand, with a source link, and checks every row against the CMS files. The map
  links a whole product line (for example every VADER pedicle system 510(k)), not the single clearance CMS reviewed.
- **The amount is a ceiling.** NTAP pays up to the maximum shown, and only when a case costs more than the MS-DRG
  pays. Pass-through pays the hospital's cost for the device, reduced to cost and less any device offset. Neither
  says what a hospital paid for the device.
- **Original Medicare only.** Commercial payers and Medicare Advantage plans set their own rules.
- **Status is for one year.** FY 2027 (inpatient) and CY 2027 (outpatient). Pass-through codes marked "during CY
  2027" expire in the year; CMS does not list the exact date in Addendum B.
- **PMA devices have no product page.** Infuse, PearlMatrix, TOPS and TOUCH CMC 1 show on company pages only.
- **An add-on payment is a payment rule,** not a finding about safety, effectiveness or value.

## Decision briefs

- **The signal cards follow fixed rules** written in `supabase/05_decision_functions.sql`. They summarize the data
  above and inherit every limitation on this page.
- **"Last five years"** is measured back from the latest clearance date in the data, not from today.
- **The questions on each card are suggestions** for a value analysis or sourcing conversation. They are not
  regulatory, legal or compliance advice.

## Plain-English names and segments

- **Plain-English product code names and the unofficial segment labels were drafted with AI help.** Names not yet
  marked reviewed in `reviews/Product_Code_Dictionary_REVIEW.xlsx` show as "pending expert review" on the site.

## Text repair

- **Some source files lost characters** (®, ™, accented letters, dashes) before the data reached the tool. The
  repair step restores a value only when FDA's own record for the same 510(k) has the same length and matches
  every other character. Anything else is left as it was and listed in `outputs/Text_Repair_Report.txt`.

## Reproducibility

- **Same inputs, same outputs.** Every export is sorted, and ties are broken by name, so two runs on the same data
  write identical CSV files. Inside the payments build, the all-years view files each surgeon under one specialty
  bucket even when the listed specialty changed between years; company dollar totals don't depend on that
  choice, but the split by specialty can shift slightly.
- **New FDA and CMS releases change the numbers.** Each data release on GitHub is dated, and `pc_meta.csv` records
  the export time and parser version.

## Medicare payments by procedure

- **Original Medicare fee-for-service only.** Medicare Advantage, Medicaid and commercial payers are not in the
  data, and commercial rates usually run higher.
- **CMS hides any hospital and DRG with fewer than 11 discharges** (11 services for outpatient), so totals and
  hospital counts run low, most for low-volume DRGs. DRG 461 and 12 other musculoskeletal surgical DRGs (476, 495,
  498, 499, 503, 505, 506 to 510 and 514) had no reportable hospital in 2024.
- **A hospital spread needs at least 5 hospitals.** Twelve DRGs fall short, mostly hand, foot, knee and hardware
  removal surgery, which has moved to outpatient care.
- **A DRG pays for the whole stay:** room, staff, operating room, drugs and supplies. No public data shows what a
  hospital pays for devices. The supply range is a planning reference from published studies, not a standard or a
  target, and it appears only for the 8 families a study covers.
- **"Patient and other payers" is what the hospital bills,** not what it collects.
- **Hip and knee replacement share DRGs 469 and 470 and APC 5115,** so the data can't separate them.
- **Outpatient groups (APCs) cover many procedures each,** so the outpatient view can't separate, say, a bunion
  repair from a wrist plate.
- **Device categories are drafted from DRG definitions and FDA anatomy,** and stay marked draft until reviewed. Real
  cases vary, and many biologics and PMA devices are outside the 510(k) data.
- **"Reviewed" device categories were checked against public sources,** not by a clinician. For the 7 families added
  in November 2026, a reviewed link means a manufacturer coding guide or the CMS DRG manual ties that device type's
  procedures to the family's DRGs. It does not mean the device shows up in a given share of cases.
- **These are 2024 DRGs** (titles from MS-DRG v41.1). CMS added new spine fusion DRGs in fiscal year 2025, and
  renumbered more on October 1, 2026 (MS-DRG v44): knee surgery with an infection diagnosis moved from DRGs 485 to 487
  to DRG 400, and hip or knee revision moved from 466 to 468 to DRG 449. Today's DRG list won't match these numbers.

## Scope of the project

OrthoParity is an independent research tool built from public FDA and CMS data, provided as is. It is not
affiliated with FDA or CMS, and it is not regulatory, legal or compliance advice. It is the author's personal work
and views.
