# Contributing

Thanks for helping. OrthoParity is only useful if its numbers are right, so reports of wrong numbers are the most
valuable contribution of all.

## Report a data problem

Open a GitHub issue with:

1. The K-number or vendor, and the page where you saw it.
2. What the site shows.
3. What it should show, with a public source (an FDA page, a 510(k) Summary page number, a CMS record, an SEC
   filing).

Please don't include anything confidential: no contract prices, no internal company documents, no information
covered by a confidentiality agreement. If a fix needs one of those to be proven, it can't go on a public site.

## Change the code

1. Fork the repository and make a branch.
2. Install: `python -m pip install -r requirements.txt` (or double-click `run.bat` on Windows).
3. Make the change. Keep each pipeline step in its own file under `pipeline/`, and put shared logic in
   `predicate_chain/`.
4. Add or update a test in `tests/`. **Tests use synthetic data only**: invented K-numbers, companies and
   payments, never real surgeon data.
5. Run `python orthoparity.py test` and `python orthoparity.py check`. Both must pass.
6. If the change alters what the site shows, add a line to `CHANGELOG.md` saying what changed and why.
7. Open a pull request. GitHub runs the tests on Windows and Linux.

## Rules the project keeps

- **Public data only.** Every number must trace back to a public FDA, CMS or SEC source.
- **Never guess.** Missing data is written as NOT FOUND with a reason, never filled in.
- **No surgeon names or NPIs**, anywhere: code, tests, docs, issues or exports. Recipients are counted with a
  salted hash, and the salt (`data/recipient_salt.txt`) is never published.
- **A dead end is not an origin.** Never label the last device in a chain "root" or "original".
- **A payment or a recall is a fact, not a verdict.** Wording on the site and in the docs stays neutral toward
  companies, surgeons, hospitals and purchasing groups.
- **Settings live in `config.ini`.** File names and expected row counts go there, not in code.
- **Rules are explicit.** Decision-brief rules stay in SQL (`supabase/05_decision_functions.sql`) where anyone can
  read them. Same input, same output.

## Database changes

Edit the numbered file in `supabase/` that holds the object. Use `create or replace` (functions) or
`if not exists` (tables and indexes) so every file stays safe to run again. Grant execute to `anon` only for
functions the website needs.

## License

By contributing you agree that your contribution is licensed under the MIT License in `LICENSE`.
