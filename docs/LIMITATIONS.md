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
- **Applicant names appear as printed at clearance.** The predicate pages don't roll them up to current owners;
  the vendor pages do.

## Vendors and ownership

- **The vendor registry groups names by rule and by review.** A curated pattern, device and 510(k) evidence, or
  the cleaned name decides which vendor a name belongs to. Unreviewed groupings can be wrong; the registry
  workbook in `reviews/` shows each one and its basis.
- **Ownership changes come from 25 dated events with sources.** Deals not in `reference/vendor_lineage.csv` are
  not reflected. Point-in-time views move a company's history to its buyer from the closing date only.
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

## Scope of the project

OrthoParity is an independent research tool built from public FDA and CMS data, provided as is. It is not
affiliated with FDA or CMS, and it is not regulatory, legal or compliance advice. It is the author's personal work
and views.
