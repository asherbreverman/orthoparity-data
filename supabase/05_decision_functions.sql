-- OrthoParity database: decision briefs (the product and vendor signal cards)
-- Part of the OrthoParity data pipeline (MIT License). Run the files in this folder in number order in the
-- Supabase SQL Editor (or psql). Every file is safe to run again. See supabase/README.md.
-- Turns the data behind each product and vendor page into a short list of signals, each with a finding, why it
-- matters and what to ask. Fixed rules only: same input, same output.

create or replace function pc_money(x double precision) returns text language sql immutable as $$
  select case when x is null then null
              when abs(x) >= 1e9 then '$' || trim(to_char(x / 1e9, 'FM999990.0')) || 'B'
              when abs(x) >= 1e6 then '$' || trim(to_char(x / 1e6, 'FM999990.0')) || 'M'
              when abs(x) >= 1e4 then '$' || trim(to_char(x / 1e3, 'FM999990')) || 'K'
              when abs(x) >= 1e3 then '$' || trim(to_char(x / 1e3, 'FM990.0')) || 'K'
              else '$' || trim(to_char(x, 'FM999990')) end
$$;

-- latest clearance date in the data; "last five years" is measured back from here
create or replace function pc_data_end() returns date language sql stable as $$
  select max(decision_date) from pc_portfolio_510k
$$;

create or replace function pc_card(key text, question text, badge text, tone text, finding text, why text, ask text,
                                   evidence text default null)
returns jsonb language sql immutable as $$
  select jsonb_build_object('key', key, 'question', question, 'badge', badge, 'tone', tone,
                            'finding', finding, 'why', why, 'ask', ask, 'evidence', evidence)
$$;

create or replace function pc_fig(v text, label text) returns jsonb language sql immutable as $$
  select case when v is null then null else jsonb_build_object('value', v, 'label', label) end
$$;

create or replace function pc_num(n numeric) returns text language sql immutable as $$
  select case when n is null then null else to_char(n, 'FM999,999,999,990') end
$$;

-- array of non-null tiles
create or replace function pc_figs(variadic f jsonb[]) returns jsonb language sql immutable as $$
  select coalesce(jsonb_agg(x), '[]'::jsonb) from unnest(f) x where x is not null
$$;

-- non-empty questions, in order, as a JSON array
create or replace function pc_asks(variadic q text[]) returns jsonb language sql immutable as $$
  select coalesce(jsonb_agg(x), '[]'::jsonb) from unnest(q) x where nullif(trim(x), '') is not null
$$;

-- whole dollars with thousands separators ($27,892)
create or replace function pc_usd(x numeric) returns text language sql immutable as $$
  select case when x is null then null
              when x = round(x) then '$' || to_char(x, 'FM999,999,999,990')
              else '$' || to_char(x, 'FM999,999,999,990.00') end
$$;

-- a payment range, or one amount when the range is a single DRG ($19,439, or $27,892 to $104,193)
create or replace function pc_pay_range(lo numeric, hi numeric, compact boolean default false) returns text language sql immutable as $$
  select case when lo is null then null
              when round(lo) = round(hi) then case when compact then pc_money(lo::double precision) else pc_usd(round(lo)) end
              when compact then pc_money(lo::double precision) || ' to ' || pc_money(hi::double precision)
              else pc_usd(round(lo)) || ' to ' || pc_usd(round(hi)) end
$$;

-- a device name cut at its first comma or semicolon ("OPTETRAK TOTAL KNEE SYSTEM, HI-FLEX ..." -> "OPTETRAK TOTAL KNEE SYSTEM")
create or replace function pc_short_name(n text) returns text language sql immutable as $$
  -- first part of a device name, cut at the first comma or semicolon outside parentheses
  -- ("GENTAFIX® (1, 3, 3MV)" stays whole instead of becoming "GENTAFIX® (1")
  select nullif(case when x.a ~ '\([^)]*$' then coalesce(trim(substring(x.f from '^[^(]*\([^)]*\)[^,]*')), x.a) else x.a end, '')
    from (select f, trim(split_part(f, ',', 1)) as a from (select split_part(coalesce(n, ''), ';', 1) as f) s) x
$$;

-- a count with its noun (1 death, 2 deaths)
create or replace function pc_count(n numeric, one text, many text) returns text language sql immutable as $$
  select pc_num(coalesce(n, 0)) || ' ' || case when coalesce(n, 0) = 1 then one else many end
$$;

-- countries as names for the questions (two-letter FDA codes; unknown codes stay as codes)
create or replace function pc_country(c text) returns text language sql immutable as $$
  select case upper(c) when 'US' then 'the United States' when 'IE' then 'Ireland' when 'CH' then 'Switzerland'
    when 'DE' then 'Germany' when 'FR' then 'France' when 'GB' then 'the United Kingdom' when 'NL' then 'the Netherlands'
    when 'IT' then 'Italy' when 'CN' then 'China' when 'KR' then 'South Korea' when 'TW' then 'Taiwan' when 'JP' then 'Japan'
    when 'CR' then 'Costa Rica' when 'MX' then 'Mexico' when 'PR' then 'Puerto Rico' when 'CA' then 'Canada'
    when 'BE' then 'Belgium' when 'SE' then 'Sweden' when 'DK' then 'Denmark' when 'AU' then 'Australia' when 'IN' then 'India'
    when 'IL' then 'Israel' when 'MY' then 'Malaysia' when 'SG' then 'Singapore' when 'PL' then 'Poland' when 'AT' then 'Austria'
    when 'ES' then 'Spain' when 'BR' then 'Brazil' when 'TR' then 'Turkey' when 'HK' then 'Hong Kong'
    when 'AE' then 'the United Arab Emirates' when 'AR' then 'Argentina' when 'BG' then 'Bulgaria' when 'BM' then 'Bermuda'
    when 'CL' then 'Chile' when 'CO' then 'Colombia' when 'CZ' then 'the Czech Republic' when 'DO' then 'the Dominican Republic'
    when 'EC' then 'Ecuador' when 'EE' then 'Estonia' when 'EG' then 'Egypt' when 'FI' then 'Finland' when 'GR' then 'Greece'
    when 'GT' then 'Guatemala' when 'HN' then 'Honduras' when 'HU' then 'Hungary' when 'ID' then 'Indonesia' when 'IS' then 'Iceland'
    when 'KH' then 'Cambodia' when 'LT' then 'Lithuania' when 'LV' then 'Latvia' when 'MT' then 'Malta' when 'NI' then 'Nicaragua'
    when 'NZ' then 'New Zealand' when 'PA' then 'Panama' when 'PE' then 'Peru' when 'PH' then 'the Philippines' when 'PK' then 'Pakistan'
    when 'PT' then 'Portugal' when 'RO' then 'Romania' when 'RU' then 'Russia' when 'SK' then 'Slovakia' when 'SM' then 'San Marino'
    when 'SV' then 'El Salvador' when 'TH' then 'Thailand' when 'UA' then 'Ukraine' when 'VN' then 'Vietnam' when 'WS' then 'Samoa'
    when 'ZA' then 'South Africa' else upper(c) end
$$;

-- a company name for sentences: legal suffixes dropped ("SI-BONE, INC." -> "SI-BONE"); an unparsed name reads "an unnamed company"
-- Phase 3: names title-cased from FDA's ALL CAPS lose their acronyms ("Tdm", "Gbs Commonwealth", "Kfx Medical").
-- A 2-4 letter word with no vowel is an acronym, except a few abbreviations.
create or replace function pc_acr(t text) returns text language plpgsql immutable as $$
declare r text := t; w text;
begin
  if r is null then return r; end if;
  for w in select distinct x[1] from regexp_matches(r, '\m([B-DF-HJ-NP-TV-Z][b-df-hj-np-tv-z]{1,3})\M', 'g') x loop
    if w not in ('Mr', 'Mrs', 'Dr', 'St', 'Ltd', 'Mfg', 'Pty', 'Gmbh', 'Bhd', 'Sdn', 'Pvt', 'Std', 'Srl', 'Sl', 'Ms', 'Jr', 'Sr', 'Nd', 'Rd', 'Th', 'Hwy', 'Mt', 'Ft', 'Kg', 'Bv', 'Llc', 'Plc', 'Ltda', 'Sprl', 'Bvba') then
      r := regexp_replace(r, '\m' || w || '\M', upper(w), 'g');
    end if;
  end loop;
  return r;
end $$;

create or replace function pc_co(n text) returns text language plpgsql immutable as $$
-- company name as FDA filed it, minus legal suffixes, trailing "(aka/dba ...)" notes, an unclosed "(" left by FDA's
-- field length limit, and a few known mangled spellings; acronyms restored by pc_acr
declare r text;
begin
  if n is null or btrim(n) = '' or n ilike 'no company name found%' then return 'an unnamed company'; end if;
  if n ilike 'PMA (not in 510(k) records)' then return n; end if;
  r := btrim(n);
  r := regexp_replace(r, '^Wrightmedicaltechnologyinc$', 'Wright Medical Technology', 'i');
  r := regexp_replace(r, '^Depuyacromed$', 'DePuy AcroMed', 'i');
  r := regexp_replace(r, '\mDepuy\s*\(\s*Ireland\s*\)', 'DePuy Ireland', 'i');
  r := regexp_replace(r, '\mDepuy\M', 'DePuy', 'g');
  r := regexp_replace(r, '\mNu ?Vasive\M', 'NuVasive', 'gi');
  r := regexp_replace(r, '\mSynthes \(Usa\)', 'Synthes USA', 'i');
  r := regexp_replace(r, '\mZimvie\M', 'ZimVie', 'g');
  r := regexp_replace(r, '\s*\((aka|a/k/a|dba|d/b/a|d\.b\.a|formerly|now|tm|r)\M[^)]*\)?\s*$', '', 'i');
  r := regexp_replace(r, '\s*\([^()]*(inc|llc|ltd|corp|corporation|stryker|surgical|biosurgery)[^()]*\)?\s*$', '', 'i');
  r := regexp_replace(r, '\s*\([^()]*$', '');
  r := regexp_replace(r, '[,\s]+(GmbH|Gmbh|GMBH)\s*(&|and|und)\s*(Co|CO)\.?\s*(Betriebs\s+)?(KG|Kg)\.?$', '', 'i');
  r := regexp_replace(r, '[,\s]+(inc|incorporated|llc|l\.l\.c|ltd|limited|corp|corporation|co|gmbh|s\.a\.s|sas|s\.a|s\.p\.a|spa|s\.r\.l|srl|b\.v|bv|n\.v|ag|se|kg|ab|uc|ulc|plc|lp|pty|ltda)\.?$', '', 'i');
  r := regexp_replace(r, '[,\s]+(inc|incorporated|llc|ltd|corp|co|gmbh)\.?$', '', 'i');
  return pc_acr(btrim(r, ' ,'));
end $$;

-- title case for names FDA files in ALL CAPS, keeping acronyms and model codes
-- ("EAUM TOTAL KNEE SYSTEM" -> "EAUM Total Knee System"; "PROXIMAL FEMORAL NAIL (PFN) SYSTEM" -> "Proximal Femoral Nail (PFN) System")
-- initcap without the server locale: Supabase's initcap treats "i.t.s." as one word and returns "I.t.s.",
-- while a C-locale server returns "I.T.S.". Capitalize each run of letters and digits ourselves.
create or replace function pc_initcap(t text) returns text language sql immutable as $$
  select coalesce(string_agg(case when x.m ~ '^[[:alnum:]]' then upper(left(x.m, 1)) || lower(substr(x.m, 2)) else x.m end, '' order by r.n), t)
    from regexp_matches(t, '([[:alnum:]]+|[^[:alnum:]]+)', 'g') with ordinality as r(a, n),
         lateral (select r.a[1] as m) x
$$;

create or replace function pc_tc(s text) returns text language plpgsql immutable as $$
declare
  w text; part text; res text; tok text; out text := ''; i int := 0; letters int; lowers int;
  keep text[] := array['PEEK','PEKK','ALIF','LLIF','TLIF','PLIF','XLIF','OLIF','ACDF','UHMWPE','MAUDE','GUDID','NTAP','HCPCS',
                       'ODEP','TKA','THA','UKA','VBR','IBF','PSI','SI-BONE','II','III','IV','VI','VII','VIII','IX','XL','XXL',
                       'MIS','MRI','USA','UK','EU','CPT','PMMA','DBM','CMF','TMJ','NAVIO','NOT','FOUND'];
  small text[] := array['AND','OR','OF','FOR','THE','WITH','TO','IN','ON','A','AN','BY','AT','VS','PER'];
  words3 text[] := array['HIP','TOE','CUP','PIN','ROD','KIT','SET','BAR','CAP','NUT','LEG','ARM','LAG','BOX','TAB','TIP','FIX',
                         'ONE','TWO','ALL','NEW','MAX','PRO','RIB','JAW','EAR','END','LOW','TOP','ARC','BUN','ACE','DUO','TRI','UNI'];
begin
  if s is null then return null; end if;
  letters := length(regexp_replace(s, '[^A-Za-z]', '', 'g'));
  lowers := length(regexp_replace(s, '[^a-z]', '', 'g'));
  if letters < 4 or lowers::numeric / letters > 0.2 then return s; end if;
  foreach w in array regexp_split_to_array(btrim(s), '\s+') loop
    i := i + 1;
    if upper(regexp_replace(w, '[,.;:]+$', '')) = any(keep) or w ~ '^\(?[A-Z]{2,4}\)?[,.;:]?$' and upper(regexp_replace(w, '[^A-Za-z]', '', 'g')) <> all(words3 || small)
       and length(regexp_replace(w, '[^A-Za-z]', '', 'g')) <= 3 then
      res := w;
    elsif upper(regexp_replace(w, '[^A-Za-z]', '', 'g')) = any(small) and i > 1 then
      res := lower(w);
    else
      res := '';
      for part in select (regexp_matches(w, '([^-/]+|[-/])', 'g'))[1] loop
        tok := regexp_replace(part, '[^A-Za-z]', '', 'g');
        if part ~ '\d' or upper(part) = any(keep) or part in ('-', '/')
           or (length(tok) between 2 and 3 and upper(tok) <> all(words3 || small) and part = upper(part) and position('(' in part) = 0 and i > 0
               and w ~ '[-/]') then
          res := res || part;
        else
          res := res || regexp_replace(pc_initcap(part), '''S\M', '''s', 'g');
        end if;
      end loop;
    end if;
    out := out || case when i > 1 then ' ' else '' end || res;
  end loop;
  return out;
end $$;

-- the last pass over every sentence a brief shows: company suffixes, ALL CAPS names, symbols, possessives,
-- dates, plurals and punctuation. Quoted FDA text (Indications for Use) never goes through it.
create or replace function pc_fix_text(t text) returns text language plpgsql immutable as $$
declare
  r text := t; m text; i int;
  mon text[] := array['January','February','March','April','May','June','July','August','September','October','November','December'];
  suf text := '(Inc|INC|Incorporated|INCORPORATED|LLC|L\.L\.C|Ltd|LTD|Limited|LIMITED|Private Limited|Pvt\. Ltd|GmbH & Co\. KG|GmbH|GMBH|Gmbh|Corp|CORP|Corporation|CORPORATION|S\.A\.S|S\.A\. de C\.V|S\.A|S\.R\.L|S\.p\.A|B\.V|N\.V|NV|AG|SAS|SA|Pty Ltd|Co\., Ltd|Co\.,Ltd|Co\. Ltd|Co Ltd|CO\., LTD|L\.P|LP|ULC|UC|PLC|plc|SE|Co|CO|Pty|\(Pty\))';
  stopw text[] := array['FDA','MAUDE','GUDID','NTAP','HCPCS','OAI','NAI','VAI','MS-DRG','MS-DRGS','ICD-10-PCS','UDI-DI','FEI','CMS','ASC','CY','FY','NOT','FOUND','NCT'];
  ok boolean;
begin
  if r is null or r = '' then return r; end if;
  -- "GmbH & Co. KG" (any casing, "and"/"und", "Betriebs") is one suffix
  if position('gmbh' in lower(r)) > 0 then
    r := regexp_replace(r, '(,\s*|\s+)(GmbH|Gmbh|GMBH)\s*(&|and|und)\s*(Co|CO)\.?\s*(Betriebs\s+)?(KG|Kg)\.?(?=[\s,;:)''’.]|$)', '', 'g');
  end if;
  -- company suffixes: drop the abbreviation's own period unless it also ends the sentence
  r := regexp_replace(r, '(,\s*|\s+)' || suf || '\.(?=\s[a-z(]|[,:;)''’])', '', 'g');
  r := regexp_replace(r, '(,\s*|\s+)' || suf || '(?=[\s,;:).''’]|$)', '', 'g');
  -- ALL CAPS names inside sentences
  for m in select distinct x[1] from regexp_matches(r, '([A-Z][A-Z0-9&''./+-]*[A-Z0-9.](?:\s+(?:[A-Z0-9][A-Z0-9&''./+-]*|&))+)', 'g') x loop
    select bool_or(length(regexp_replace(w, '[^A-Z]', '', 'g')) >= 5 and upper(w) <> all(stopw))
      into ok from unnest(regexp_split_to_array(m, '\s+')) w;
    if ok and m !~ 'NOT FOUND' then r := replace(r, m, pc_tc(m)); end if;
  end loop;
  r := replace(replace(replace(r, '(R)', '®'), '(TM)', '™'), '(tm)', '™');
  -- possessives: "DePuy Synthes (Johnson & Johnson)'s" -> "DePuy Synthes'", "IsoTis OrthoBiologics's" -> "IsoTis OrthoBiologics'"
  r := regexp_replace(r, ' \([^()]*\)''s\M', '''s', 'g');
  r := regexp_replace(r, '([a-z])s''s\M', '\1s''', 'g');
  r := regexp_replace(r, 'equivalent to 1 of (.+?)''s? own earlier device\M', 'equivalent to an earlier \1 device', 'g');
  r := replace(r, 'Cleared against 1 of ', 'Cleared against one of ');
  -- dates in sentences: "on 2025-04-21" -> "in April 2025"
  for i in 1..12 loop
    r := regexp_replace(r, 'on (\d{4})-' || lpad(i::text, 2, '0') || '-\d\d', 'in ' || mon[i] || ' \1', 'g');
  end loop;
  -- plurals after 1
  r := regexp_replace(r, '\m1 ((?:other |orthopedic |adverse event |industry-funded |FDA-registered |recall |research |product )?)(compan|stud|categor|injur|countr|famil|technolog)ies\M', '1 \1\2y', 'g');
  r := regexp_replace(r, '\m1 ((?:other |orthopedic |adverse event |industry-funded |FDA-registered |recall |research |catalog |partner |company |warning |MAUDE |device |OAI |open |product )?)(clearance|site|report|recall|device|item|brand|event|time|predicate|code|generation|peer|consultant|recipient|physician|death|malfunction|payment|surgeon|inspection|letter|product|partner|MS-DRG|510\(k\))s\M', '1 \1\2', 'g');
  r := regexp_replace(r, '\m1 ((?:[A-Za-z-]+ )?)(site|report|study|company|clearance|brand) (list|name|make)\M', '1 \1\2 \3s', 'g');
  r := regexp_replace(r, '\m1 ((?:[A-Za-z-]+ )?)(consultant|recipient|physician|device|other device) were\M', '1 \1\2 was', 'g');
  r := regexp_replace(r, '\m1 ((?:[A-Za-z-]+ )?)(clearance|study|report)s? have\M', '1 \1\2 has', 'g');
  -- zero counts read as words
  r := regexp_replace(r, '; 0 in the last five years \(0 deaths, 0 injuries, 0 malfunctions\)', '; none in the last five years', 'g');
  r := regexp_replace(r, '(^|\. )0 recall events in the last five years', '\1No recall events in the last five years', 'g');
  r := regexp_replace(r, '(^|\. )0 warning letters in the last five years', '\1No warning letters in the last five years', 'g');
  -- punctuation
  r := regexp_replace(r, '\.\.(?!\.)', '.', 'g');
  r := regexp_replace(r, '\s+,', ',', 'g');
  r := regexp_replace(r, ',{2,}', ',', 'g');
  r := regexp_replace(r, '\.([,:;])', '\1', 'g');
  r := regexp_replace(r, ',\.', '.', 'g');
  r := regexp_replace(r, '[ ]{2,}', ' ', 'g');
  return btrim(r);
end $$;

-- the same pass over a card: every sentence, question and tile label (the quoted Indications for Use stay as filed)
create or replace function pc_fix_card(c jsonb) returns jsonb language plpgsql immutable as $$
declare k text; r jsonb := c;
begin
  if c is null then return null; end if;
  foreach k in array array['badge', 'finding', 'why', 'ask', 'headline'] loop
    if r ? k and jsonb_typeof(r->k) = 'string' and not (k = 'finding' and c->>'key' = 'indications') then
      r := jsonb_set(r, array[k], to_jsonb(pc_fix_text(r->>k)));
    end if;
  end loop;
  -- badges are labels, not sentences ("Now Kyocera Medical." -> "Now Kyocera Medical")
  if jsonb_typeof(r->'badge') = 'string' then
    r := jsonb_set(r, '{badge}', to_jsonb(regexp_replace(r->>'badge', '(?<!\m[A-Z]|\mCo|\mInc|\mLtd)\.$', '')));
  end if;
  if jsonb_typeof(r->'asks') = 'array' then
    r := jsonb_set(r, '{asks}', (select coalesce(jsonb_agg(to_jsonb(pc_fix_text(x))), '[]'::jsonb) from jsonb_array_elements_text(r->'asks') x));
  end if;
  if jsonb_typeof(r->'figs') = 'array' then
    r := jsonb_set(r, '{figs}', (select coalesce(jsonb_agg(f || jsonb_build_object('label',
           case when f->>'value' = '1' then substr(pc_fix_text('1 ' || (f->>'label')), 3) else pc_fix_text(f->>'label') end)), '[]'::jsonb)
         from jsonb_array_elements(r->'figs') f));
  end if;
  return r;
end $$;

-- do two company names refer to the same company? (first distinctive word of the 510(k) holder appears in the owner's name)
create or replace function pc_same_name(a text, b text) returns boolean language sql immutable as $$
  select coalesce(bool_or(position(w in regexp_replace(lower(coalesce(b, '')), '[^a-z]', '', 'g')) > 0), true)
    from unnest(regexp_split_to_array(lower(regexp_replace(coalesce(a, ''), '[^A-Za-z ]', ' ', 'g')), '\s+')) w
   where length(w) >= 3 and w not in ('the', 'and', 'inc', 'llc', 'ltd', 'corp', 'dba', 'medical', 'orthopedic', 'orthopedics',
                                      'orthopaedics', 'orthopaedic', 'surgical', 'spine', 'spinal', 'technologies', 'technology', 'international',
                                      'usa', 'company', 'group', 'systems', 'devices', 'innovations', 'solutions', 'products', 'reconstructive')
$$;

-- Indications for Use text with FDA form text, contact details and page marks removed; null when what is left
-- doesn't read as an indication (a cover letter, a form header or too short)
create or replace function pc_clean_ifu(t text) returns text language plpgsql immutable as $$
declare r text := coalesce(t, '');
begin
  r := regexp_replace(r, '(Indications )?for Use\s*21 CFR 807\.92\(a[)}]\(5\)', ' ', 'gi');
  r := regexp_replace(r, '(Indications for Use )?Comparison\s*21 CFR 807\.92\(a[)}]\(5\)', ' ', 'gi');
  r := regexp_replace(r, '21 CFR 807\.92\(a[)}]\(5\)', ' ', 'gi');
  r := regexp_replace(r, 'Indications for Use Comparison', ' ', 'gi');
  r := regexp_replace(r, 'Type of Use \(Select one or both, as applicable\)', ' ', 'gi');
  r := regexp_replace(r, 'K\d{6}\s*-\s*Page \d+ of \d+|Page \d+ of \d+', ' ', 'gi');
  r := btrim(regexp_replace(r, '\s+', ' ', 'g'));
  -- Phase 3: form labels left at the start ("510(k) Number (if known) ... Device Name: ... Indications for Use:", "Statement")
  r := regexp_replace(r, '^510\(k\) Number \(if known\)\s*:?\s*(K\d{6})?\s*(Device Name\s*:?.*?(Indications for Use|INDICATIONS)\s*(Statement)?\s*:?\s*)?', '', 'i');
  r := regexp_replace(r, '^(Indications for Use Statement|Indications for Use|Indications|Statement)\s*:?\s+', '', 'i');
  r := regexp_replace(r, '^(Statement)\s*:?\s+', '', 'i');
  -- "o Shoulder:" bullets from Word lists
  r := regexp_replace(r, '(^|[.:;]\s+|\s)o (?=[A-Z])', '\1• ', 'g');
  if r ~* '(FOR FDA USE ONLY|Concurrence of Center|PRA Statement|Form FDA|Sincerely|Dear |Prescription Use|Over-The-Counter Use)'
     or r ~ '[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}'
     or r ~ '(\(?\d{3}\)?[-. ]\d{3}[-. ]\d{4}|\m\d{10}\M|\+?\d{1,3}[- ]\d{1,4}[- ]\d{3,4}[- ]\d{4})'
     or r ~ '\m(Mr|Ms|Mrs|Dr)\.\s+[A-Z][a-z]+'
     or r ~ '\m[A-Z]{2} \d{5}(-\d{4})?\M' or r ~* 'United States \d'
     or length(r) < 60 then
    return null;
  end if;
  return r;
end $$;

-- What is it cleared to treat? This 510(k)'s Indications for Use and how closely the wording matches its primary
-- predicate's (trigram similarity on the extracted text; a wording comparison, not a clinical judgment)
create or replace function pc_device_indications(k text) returns jsonb language sql stable as $$
  with me as (select ifu_text, page from pc_ifu where knumber = k and coalesce(ifu_text, '') <> ''),
  pred as (
    select e.predicate, d.device_name, i.ifu_text
    from pc_edges e left join pc_devices d on d.knumber = e.predicate
    left join pc_ifu i on i.knumber = e.predicate and coalesce(i.ifu_text, '') <> ''
    where e.child = k
    order by (e.role = 'primary') desc, e.list_order nulls last, e.predicate limit 1)
  select jsonb_build_object(
    'knumber', k,
    'found', exists (select 1 from me),
    'ifu_text', (select ifu_text from me), 'page', (select page from me),
    'predicate', (select jsonb_build_object('knumber', predicate, 'device_name', device_name, 'ifu_text', ifu_text) from pred),
    'similarity', (select round(similarity(lower(me.ifu_text), lower(pred.ifu_text))::numeric, 2) from me, pred
                   where pred.ifu_text is not null))
$$;

-- how well a device's own words fit a Medicare procedure family (0 = no anatomy or procedure word in common)
create or replace function pc_family_score(fam text, dtext text) returns int language sql immutable as $$
  select case fam
    when 'cervical_fusion' then case when dtext ~ '(cervical|acdf|occipit|\mc1\M|\mc2\M|odontoid)' then 3 else 0 end
    when 'thoracolumbar_fusion' then case when dtext ~ '(lumbar|thoracolumbar|pedicle|interbody|\mtlif|\mplif|\malif|\mllif|\mxlif|\molif|sacr(o|al)(?!iliac)|scolio|deformity|vertebral body|kypho)' then 3
                                          when dtext ~ '(spin|vertebr|facet)' then 1 else 0 end
    when 'spine_surgery_no_fusion' then case when dtext ~ '(lamin|decompress|interspinous|spinous process|stenosis|disc replacement|disc prosthes|motion preserv)' then 3 else 0 end
    when 'hip_knee_replacement' then case when dtext ~ '(knee|\mtka\M|\mtha\M|\muka\M|acetab|tibial (tray|insert|base|component)|patell|unicompart|femoral component|total hip|hip (system|stem|prosthes|replacement|arthroplasty|cup)|\mhip\M)' then 3 else 0 end
    when 'revision_hip_knee' then case when dtext ~ '(revision|augment|\mcone\M|sleeve|hinge|constrained)' then 4 else 0 end
    when 'hip_fracture_replacement' then case when dtext ~ '(hemiarthroplasty|bipolar|unipolar|endoprosthes)' then 4 else 0 end
    when 'hip_femur_fixation' then case when dtext ~ '(femur|femoral nail|trochant|hip fracture|hip screw|proximal femoral|cephalomedullary|femoral neck|hip pin)' then 4 else 0 end
    when 'lower_extremity_humerus' then case when dtext ~ '(tibia|tibial nail|humer|fibula|pilon|plateau|external fix|fixator|ring fix|hexapod)' then 3 else 0 end
    when 'foot_soft_tissue' then case when dtext ~ '(foot|ankle|\mtoe|hallux|bunion|metatars|calcane|talus|talar|lapidus|hammer|achilles|plantar|cuneiform|subtalar)' then 3 else 0 end
    when 'shoulder_elbow_replacement' then case when dtext ~ '(shoulder (arthroplasty|prosthes|system|replacement)|total shoulder|reverse shoulder|glenoid|humeral (head|stem)|stemless|elbow (arthroplasty|prosthes|system)|total elbow|radial head)' then 4
                                                when dtext ~ 'shoulder' then 1 else 0 end
    when 'upper_extremity_no_replacement' then case when dtext ~ '(rotator|\mcuff|labr|bicep|clavic|radius|radial|ulna|wrist|\mhand\M|finger|carpal|scaphoid|olecranon|forearm|acromio|tendon|shoulder)' then 3 else 0 end
    when 'knee_surgery_no_replacement' then case when dtext ~ '(\macl\M|\mpcl\M|menisc|cruciate|arthroscop|tibial tubercle|osteotomy|cartilage|osteochondral|patellofemoral)' then 3 else 0 end
    when 'debridement_biopsy_amputation' then case when dtext ~ '(antibiotic|infect|osteomyelitis|amputation|debride)' then 3 else 0 end
    when 'hardware_removal' then case when dtext ~ '(removal|extraction)' then 3 else 0 end
    else 0 end
$$;

create or replace function pc_family_conflict(fams text[], dtext text) returns text language sql immutable as $$
  -- the one mismatch the stress tests found: spine devices (spinal endoscopes, discectomy probes) filed under
  -- codes mapped only to knee or upper-extremity procedures. Other name/code differences stay with the code's mapping.
  select case when dtext ~ '(\mspin(e|al)\M|lumbar|cervical|vertebr|discectom|foramin|sacroiliac)'
               and not (fams && array['thoracolumbar_fusion', 'cervical_fusion', 'spine_surgery_no_fusion'])
              then 'spine surgery' end
$$;

create or replace function pc_signals(k text)
returns jsonb language plpgsql stable as $$
declare
  kn text := upper(regexp_replace(coalesce(k, ''), '[\s\-]', '', 'g'));
  b jsonb; dev jsonb; pcode jsonb; lin jsonb;
  pattern text; company text; code text; plain text; vend text; owner text; owner_name text;
  n_direct int; n_same int; others text; prim text; gens int; lin_end text;
  data_end date; n_alt int; alts jsonb; alt_names text;
  tot double precision; roy double precision; cons double precision; yr_min int; yr_max int;
  n_st int; st_amt double precision; st_last int;
  skus int; skus_in int; med_skus double precision;
  cards jsonb := '[]'::jsonb; c_nov jsonb; c_alt jsonb; c_pay jsonb; c_ev jsonb; c_cat jsonb;
  c_ind jsonb; c_own jsonb; c_rec jsonb; c_ae jsonb; c_sup jsonb; c_med jsonb; c_add jsonb;
  bl text; crowd text;
  ind jsonb; sim numeric; own jsonb; mau jsonb; sup jsonb; addon jsonb; procs jsonb;
  fam_id text; fam_name text; fam_status text; n_fam int; drg_n int; drg_min numeric; drg_max numeric; fam_avg numeric;
  fam_dis numeric; sup30 numeric; sup50 numeric; data_yr int; n_nct int; nct_ids text; pred_recalls int;
  n_peers int; n_code int; r5 int; d5 int; i5 int; m5 int; partners text; countries text; flagged text;
  ntap_amt numeric; ntap_name text; tpt_code text; cat_tech text;
  days_new int; is_new boolean; is_capital boolean; dtext text; peer_names text; addon_lead text := '';
  is_recent boolean; is_denovo boolean; is_label boolean; has_summary boolean; dec_year int; ifu_clean text;
  tot1 double precision; brand_name text; brand_only boolean; fam_match boolean; fam_list text; fam_other text; fam_id2 text; fam_name2 text; fam_status2 text; fam_from_ifu boolean := false; seg_fams text[]; ft_parent text; ft_from date; o5 int; mau_first int; dl text;
  wl5 int; oai5 int; chain text;
begin
  b := pc_brief(kn);
  if not coalesce((b->>'found')::boolean, false) then
    return jsonb_build_object('found', false, 'knumber', kn);
  end if;
  dev := b->'device'; pcode := b->'product_code'; lin := b->'lineage';
  pattern := b->>'pattern';
  company := dev->>'applicant';
  code := dev->>'product_code';
  plain := coalesce(pcode->>'plain_name', pcode->>'fda_name', code);
  data_end := pc_data_end();

  select p.vendor_id, coalesce(nullif(x.rolls_up_to, ''), x.vendor_id) into vend, owner
    from pc_portfolio_510k p join pc_vendors x on x.vendor_id = p.vendor_id where p.knumber = kn;
  select display_name into owner_name from pc_vendors where vendor_id = owner;
  select coalesce(display_name, company) into company from pc_vendors where vendor_id = vend;
  company := pc_co(coalesce(company, dev->>'applicant'));
  owner_name := pc_co(owner_name);
  -- a clearance in its first 120 days: FDA's GUDID, registration and summary records often trail it
  days_new := data_end - nullif(dev->>'decision_date', '')::date;
  is_new := coalesce(days_new, 9999) <= 120;
  is_capital := coalesce(pcode->>'kind', '') in ('capital equipment', 'software');
  dtext := lower(coalesce(dev->>'device_name', '') || ' ' || coalesce(plain, ''));
  -- records for clearances under a year old are often incomplete (GUDID listings, yearly registration updates)
  is_recent := coalesce(days_new, 9999) <= 365;
  is_denovo := kn like 'DEN%';
  is_label := coalesce(dev->>'device_name', '') ~* '(\mMR\M.*(label|conditional|safety)|\mMRI\M.*(label|conditional|safety)|\mlabeling\M)';
  has_summary := coalesce(dev->>'summary_url', '') <> '';
  dec_year := extract(year from nullif(dev->>'decision_date', '')::date)::int;

  -- 1. Is it new?
  select count(*), count(*) filter (where (e->>'same_company')::boolean),
         (array_agg(coalesce(e->>'device_name', '') || ' (' || (e->>'predicate') || ')') filter (where e->>'role' = 'primary'))[1],
         string_agg(distinct pc_co(e->>'applicant'), ', ') filter (where not (e->>'same_company')::boolean)
    into n_direct, n_same, prim, others
    from jsonb_array_elements(coalesce(b->'direct_predicates', '[]'::jsonb)) e;
  gens := nullif(lin->>'generations', '')::int;
  if coalesce(gens, 0) > 1 then
    lin_end := ' The predicate record goes back ' || gens || ' generations to ' || coalesce(lin->'ends_at'->>'device_name', 'an earlier device')
               || ' (' || pc_co(lin->'ends_at'->>'applicant') || ', ' || coalesce(lin->'ends_at'->>'decision_year', 'year unknown') || ').';
  else
    lin_end := '';
  end if;
  c_nov := case pattern
    when 'line extension' then pc_card('novelty', 'Is it new?', 'Line extension', 'info',
      'Cleared as equivalent to ' || n_direct || ' of ' || company || '''s own earlier device' || case when n_direct = 1 then '' else 's' end
        || coalesce(', led by ' || prim, '') || '.' || lin_end,
      'An update to a product line the company already sells. It often fits an existing contract tier rather than a new line item.',
      'What changed clinically or technically from the earlier version, and will the earlier version stay available and on contract?',
      'predicates')
    when 'competitive entry' then pc_card('novelty', 'Is it new?', 'Competitive entry', 'info',
      'Cleared as equivalent to devices from ' || coalesce(others, 'other companies') || '.' || lin_end,
      'The company is entering a category where other vendors'' devices set the benchmark. Compare it with what you already use.',
      'Which product on our shelf would this replace, and what does it do better?',
      'predicates')
    when 'mixed' then pc_card('novelty', 'Is it new?', 'Builds on own and others'' devices', 'info',
      'Cleared against ' || n_same || ' of ' || company || '''s own devices and ' || (n_direct - n_same) || ' from other companies ('
        || coalesce(others, 'not named') || ').' || lin_end,
      'Builds on the company''s own line and on features cleared for other vendors'' devices.',
      'Which features came from the other companies'' devices, and what evidence supports them?',
      'predicates')
    else case
      when is_denovo then pc_card('novelty', 'Is it new?', 'De Novo: first of its kind', 'attention',
        'FDA authorized it through the De Novo pathway, which is for new types of devices with no legally marketed predicate. '
          || 'De Novo devices set up their own product code, here ' || coalesce(code, 'not on file') || ', and later devices of the type can cite them.',
        'The strongest sign of real novelty in FDA''s records. Evidence and special controls matter more than for a 510(k).',
        'What clinical data did FDA review for the De Novo, and which special controls apply?',
        'predicates')
      when is_new then pc_card('novelty', 'Is it new?', 'Predicates not posted yet', 'info',
        'FDA has not posted the 510(k) summary that lists its predicates yet. The clearance is ' || days_new || ' days old.',
        'Novelty can''t be judged until the summary is posted.',
        'Which devices did FDA clear it against, with their 510(k) numbers?',
        'predicates')
      when not has_summary then pc_card('novelty', 'Is it new?', 'No summary on file', 'info',
        'FDA''s record for this clearance has no 510(k) summary, so its predicates are not on file.'
          || case when dec_year < 1996 then ' Clearances before 1996 rarely have one.' else '' end,
        'Novelty can''t be judged from the FDA record alone.',
        'Which devices did FDA clear it against, with their 510(k) numbers?',
        'predicates')
      else pc_card('novelty', 'Is it new?', 'Predicate not on file', 'attention',
        'We could not read a predicate 510(k) number in the FDA''s summary for this clearance.',
        'Novelty can''t be judged from the FDA record alone.',
        'Which devices did FDA clear it against, with their 510(k) numbers?',
        'predicates') end end;
  if is_label then
    c_nov := c_nov || jsonb_build_object('badge', 'Labeling update', 'tone', 'info',
      'finding', 'This 510(k) updates labeling, such as MR safety conditions, for a device already on the market. ' || (c_nov->>'finding'),
      'ask', 'Does this labeling change affect how our facility scans patients with this implant, and has the instructions for use been updated in our system?');
  end if;

  -- 2. What else does this job? (other companies, same product code, last five years; grouped by current owner)
  with recent as (
    select coalesce(nullif(x.rolls_up_to, ''), x.vendor_id) as grp, p.knumber, p.device_name, p.decision_date
    from pc_portfolio_510k p join pc_vendors x on x.vendor_id = p.vendor_id
    where p.product_code = code and p.decision_date > data_end - interval '5 years'),
  g as (
    select r.grp, count(*) as clearances,
           (array_agg(r.knumber order by r.decision_date desc, r.knumber desc))[1] as latest_knumber,
           (array_agg(r.device_name order by r.decision_date desc, r.knumber desc))[1] as latest_device,
           max(r.decision_date) as latest_date
    from recent r where r.grp is distinct from owner group by r.grp)
  select count(*),
         coalesce(jsonb_agg(jsonb_build_object('vendor_id', g.grp, 'company', pc_fix_text(pc_co(v.display_name)), 'clearances', g.clearances,
                                               'latest_knumber', g.latest_knumber, 'latest_device', g.latest_device,
                                               'latest_date', g.latest_date)
                            order by g.clearances desc, g.latest_date desc, v.display_name), '[]'::jsonb),
         (array_to_string((array_agg(pc_co(v.display_name) order by g.clearances desc, g.latest_date desc, v.display_name))[1:3], ', '))
    into n_alt, alts, alt_names
    from g join pc_vendors v on v.vendor_id = g.grp;
  -- closest equivalents: other companies' devices that share this device's predicates, most shared first
  -- grouped by current owner, so a sister company or the new owner never counts as an equivalent
  select string_agg(co, ', ' order by ns desc, nd desc, latest desc, co) into peer_names from (
    select pc_co(v.display_name) as co, max((x->>'n_shared')::int) as ns, count(*) as nd, max(x->>'decision_year') as latest
      from jsonb_array_elements(coalesce(b->'peers'->'peers', '[]'::jsonb)) x
      join pc_portfolio_510k pp on pp.knumber = x->>'knumber'
      join pc_vendors pv on pv.vendor_id = pp.vendor_id
      join pc_vendors v on v.vendor_id = coalesce(nullif(pv.rolls_up_to, ''), pv.vendor_id)
     where v.vendor_id is distinct from owner
     group by 1 order by 2 desc, 3 desc, 4 desc, 1 limit 3) z;
  crowd := case when n_alt >= 20 then 'Crowded' when n_alt >= 5 then 'Competitive' when n_alt >= 1 then 'Few alternatives'
                else 'No recent alternatives' end;
  c_alt := pc_card('alternatives', 'What else does the job?', crowd, case when n_alt < 5 then 'attention' else 'info' end,
    case when n_alt > 0 then n_alt || ' other compan' || case when n_alt = 1 then 'y' else 'ies' end || ' cleared devices in product code ' || code
           || ' (' || plain || ') in the last five years of data, including ' || alt_names || '.'
         else 'No other company cleared a device in product code ' || code || ' (' || plain || ') in the last five years of data.' end
    || coalesce(' Also cleared on the same predicates: ' || peer_names || '.', ''),
    case when n_alt >= 20 then 'Plenty of substitutes. Standardizing on fewer vendors in this category is realistic.'
         when n_alt >= 5 then 'Several substitutes exist, so a head-to-head comparison is practical.'
         when n_alt >= 1 then 'Few substitutes. Supply continuity and backup options matter more.'
         else 'Little recent competition. Supply continuity matters more.' end,
    case when is_capital then 'Which competing systems did you evaluate against, and what is the total cost per case at our volume, including service and disposables?'
         when peer_names is not null then 'How does it compare with devices from ' || peer_names || ', cleared on the same predicates, and with the market leaders in this code, on outcomes, instrument sets and total cost per case?'
         when n_alt >= 5 then 'How does it compare with products from ' || alt_names || ' on outcomes, instrument sets and total cost per case?'
         else 'If supply is interrupted, what is the backup?' end,
    'alternatives');

  -- 3. Financial ties (CMS Open Payments, payments naming this 510(k) or its brand)
  select sum(amount), sum(amount) filter (where nature_group = 'royalty'), sum(amount) filter (where nature_group = 'consulting'),
         min(year), max(year), sum(amount) filter (where tier = 1),
         (array_agg(brand order by amount desc, brand) filter (where tier = 2 and coalesce(brand, '') <> ''))[1]
    into tot, roy, cons, yr_min, yr_max, tot1, brand_name
    from pc_op_product where knumber = kn;
  -- a brand match covers every version sold under the brand, including ones cleared before this 510(k)
  brand_only := coalesce(tot, 0) > 0 and coalesce(tot1, 0) < 0.5 * tot and brand_name is not null;
  c_pay := pc_card('payments', 'What are the financial ties for this product?',
    case when coalesce(roy, 0) > 0 then 'Royalties paid' when coalesce(tot, 0) > 0 then 'Payments named' else 'None named' end,
    case when coalesce(roy, 0) > 0 then 'attention' else 'info' end,
    case when coalesce(tot, 0) > 0 then
           pc_money(tot) || ' in reported payments named ' || case when brand_only then 'the ' || pc_tc(brand_name) || ' brand' else 'this product' end
           || case when yr_min = yr_max then ' in ' || yr_min
                                                                               else ' from ' || yr_min || ' to ' || yr_max end
           || case when coalesce(roy, 0) > 0 and coalesce(cons, 0) > 0 then ', including ' || pc_money(roy) || ' in royalties and ' || pc_money(cons) || ' in consulting.'
                   when coalesce(roy, 0) > 0 then ', including ' || pc_money(roy) || ' in royalties.'
                   when coalesce(cons, 0) > 0 then ', including ' || pc_money(cons) || ' in consulting. No royalties named it.'
                   else '. No royalties or consulting named it.' end
           || case when brand_only and yr_min < dec_year then ' Payments before ' || dec_year || ' went to earlier versions under the brand; this 510(k) was cleared in ' || dec_year || '.'
                   when brand_only then ' The brand covers every version sold under it, not only this 510(k).' else '' end
         else 'No Open Payments records from 2019 to 2025 name this 510(k) or its brand.' end,
    case when coalesce(roy, 0) > 0 then 'Device royalties typically go to inventors and design surgeons. Your conflict-of-interest review should know if a requesting surgeon is one.'
         when coalesce(tot, 0) > 0 then 'Shows the company''s spending tied to this product. It says nothing about any one surgeon.'
         else 'Payments may still exist under the company without a product named.' end,
    'Will you disclose every financial relationship ' || company || ' has with our requesting surgeons, as our conflict-of-interest policy requires?',
    'payments');

  -- 4. Evidence (industry-funded research in Open Payments that names this 510(k))
  select count(distinct study_name), sum(amount), max(year) into n_st, st_amt, st_last
    from pc_op_research
    where ('|' || coalesce(knumbers, '') || '|') like '%|' || kn || '|%' and coalesce(ortho, true);
  c_ev := pc_card('evidence', 'What clinical evidence exists?',
    case when n_st > 0 then n_st || ' industry-funded' else 'None in Open Payments' end,
    case when coalesce(n_st, 0) = 0 and (pattern = 'competitive entry' or is_denovo) then 'attention' else 'info' end,
    case when n_st > 0 then n_st || ' industry-funded research stud' || case when n_st = 1 then 'y names' else 'ies name' end
                            || ' this 510(k) (' || pc_money(st_amt) || ' reported, latest ' || st_last || ').'
         else 'No industry-funded research in Open Payments names this 510(k).' end
    || ' Published studies and registry data are not included yet.',
    case when n_st > 0 then 'The company is collecting data on this device. Ask for results, not just enrollment.'
         else 'Evidence may rest on predicate devices or on studies outside Open Payments.' end,
    'What clinical data exists for this device itself, as opposed to its predicates?',
    'research');

  -- 5. Catalog size (FDA GUDID device IDs that cite this 510(k))
  select gudid_devices, gudid_in_distribution into skus, skus_in from pc_portfolio_510k where knumber = kn;
  select percentile_cont(0.5) within group (order by gudid_devices) into med_skus
    from pc_portfolio_510k where product_code = code and gudid_devices > 0;
  c_cat := pc_card('catalog', 'What will it take to stock on the shelf?',
    case when coalesce(skus, 0) = 0 and is_recent then 'Not yet in GUDID'
         when coalesce(skus, 0) = 0 then 'No GUDID match'
         when skus_in < skus then (skus - skus_in) || ' discontinued'
         else skus || ' catalog items' end,
    case when skus_in < skus then 'attention' else 'info' end,
    case when coalesce(skus, 0) > 0 then
           'FDA''s GUDID lists ' || pc_count(skus, 'device ID (catalog item)', 'device IDs (catalog items)') || ' under this 510(k), ' || skus_in || ' in commercial distribution.'
           || coalesce(' The median for this category is ' || round(med_skus)::int || '.', '')
         when is_recent then 'No GUDID device IDs cite this 510(k) yet. It was cleared ' || days_new || ' days before this data release, and GUDID listings for clearances under a year old are often incomplete.'
         else 'No GUDID device record lists this 510(k) number. That usually means the labels cite an earlier or later 510(k), or leave the field blank. Ask the vendor for the part-number list.' end
    || case when is_capital then ' For capital equipment, the cost to own matters more than catalog size.' else '' end,
    'Each device ID is a line in your item master. Larger catalogs mean more items to load, more trays and more inventory.',
    case when is_capital then 'What does it cost to own per year: purchase or lease, service contract, software updates and per-case disposables?'
         when coalesce(skus, 0) > 0 then 'How many trays per case, and are sets loaner, consigned or sterile-packed?'
         else 'Is every item listed in GUDID with a UDI-DI we can load into our item master?' end,
    'catalog');

  -- short statement headlines for the page design (one per card)
  c_nov := c_nov || jsonb_build_object('headline', case pattern
             when 'line extension' then 'An update to its own line.'
             when 'competitive entry' then 'A new entry against other companies'' devices.'
             when 'mixed' then 'Built on its own and other companies'' designs.'
             else case when is_denovo then 'First of its kind (De Novo).' when is_new then 'Predicates not posted yet.' else 'No predicate on file.' end end);
  c_alt := c_alt || jsonb_build_object('headline', case when n_alt > 0
             then n_alt || ' other compan' || case when n_alt = 1 then 'y makes' else 'ies make' end || ' one.'
             else 'No recent competitors.' end);
  c_pay := c_pay || jsonb_build_object('headline', case
             when coalesce(roy, 0) > 0 then pc_money(tot) || ' in payments, including royalties.'
             when coalesce(tot, 0) > 0 then pc_money(tot) || ' in payments. No royalties.'
             else 'No payments name it.' end);
  c_ev := c_ev || jsonb_build_object('headline', case when n_st > 0
             then n_st || case when n_st = 1 then ' study names it.' else ' studies name it.' end
             else 'No studies name it.' end);
  c_cat := c_cat || jsonb_build_object('headline', case when coalesce(skus, 0) > 0
             then skus || ' catalog items.' when is_recent then 'Not yet in GUDID.' else 'No GUDID match.' end);
  -- stat tiles and short labels for the page design
  c_nov := c_nov || jsonb_build_object('short', 'New', 'figs', pc_figs(
             pc_fig(pc_num(n_same), 'of ' || company || '''s own devices'),
             pc_fig(pc_num(n_direct - n_same), 'from other companies'),
             pc_fig(pc_num(gens), 'generations on record'),
             pc_fig(lin->'ends_at'->>'decision_year', 'earliest predicate on record')));
  c_alt := c_alt || jsonb_build_object('short', 'Alternatives', 'figs', pc_figs(
             pc_fig(pc_num(n_alt), 'other companies by current owner, last five years'),
             pc_fig(pc_num((b->'peers'->>'total')::numeric), 'peers on the same predicates'),
             pc_fig(pc_num((b->'category'->>'total')::numeric), 'clearances in ' || code)));
  c_pay := c_pay || jsonb_build_object('short', 'Financial ties', 'figs', case when coalesce(tot, 0) > 0 then pc_figs(
             pc_fig(pc_money(tot), case when brand_only then 'in payments naming its brand, ' else 'in payments naming it, ' end || yr_min || ' to ' || yr_max),
             case when coalesce(roy, 0) > 0 then pc_fig(pc_money(roy), 'royalties') end,
             case when coalesce(cons, 0) > 0 then pc_fig(pc_money(cons), 'consulting') end)
           else pc_figs(pc_fig('0', 'Open Payments records naming it, 2019 to 2025')) end);
  c_ev := c_ev || jsonb_build_object('short', 'Evidence', 'figs', pc_figs(
             pc_fig(pc_num(coalesce(n_st, 0)), 'industry-funded studies naming it'),
             case when n_st > 0 then pc_fig(pc_money(st_amt), 'reported research payments') end,
             case when n_st > 0 then pc_fig(st_last::text, 'latest year') end));
  c_cat := c_cat || jsonb_build_object('short', 'Stocking', 'figs', pc_figs(
             pc_fig(pc_num(coalesce(skus, 0)), 'catalog items in GUDID'),
             case when skus > 0 then pc_fig(pc_num(skus_in), 'in commercial distribution') end,
             pc_fig(pc_num(round(med_skus::numeric)), 'category median')));

  -- what the cards below ask (several questions per card where the data supports them; the first is the card's ask)
  n_peers := nullif(b->'peers'->>'total', '')::int;
  n_code := nullif(b->'category'->>'total', '')::int;
  c_nov := c_nov || jsonb_build_object('asks', pc_asks(c_nov->>'ask',
             case when coalesce(n_peers, 0) > 0 then pc_num(n_peers) || ' other device' || case when n_peers = 1 then ' was' else 's were' end
                  || ' cleared on the same predicates. How does this one differ from them?' end));
  c_alt := c_alt || jsonb_build_object('asks', pc_asks(c_alt->>'ask',
             case when coalesce(n_code, 0) >= 5 then pc_num(n_code) || ' 510(k)s share product code ' || code
                  || '. What separates this device from the others in the code, beyond what its 510(k) summary says?' end));
  if code is null then
    c_alt := c_alt || jsonb_build_object('badge', 'No product code', 'tone', 'info', 'headline', 'No product code on file.',
      'finding', 'NOT FOUND: FDA''s record for this clearance lists no product code, so OrthoParity can''t count alternatives.',
      'ask', 'Which FDA product code and product category does this device fall under, and which devices do you consider its competitors?',
      'figs', '[]'::jsonb,
      'asks', pc_asks('Which FDA product code and product category does this device fall under, and which devices do you consider its competitors?'));
  end if;
  c_pay := c_pay || jsonb_build_object('asks', pc_asks(c_pay->>'ask',
             case when coalesce(tot, 0) > 0 then 'Explain the ' || pc_money(tot) || ' in industry payments that name ' || case when brand_only then 'the ' || pc_tc(brand_name) || ' brand' else 'this product' end
                  || ': how much was royalties, consulting, education, travel and meals?' end));
  select count(distinct ct_gov_id) filter (where coalesce(ct_gov_id, '') <> ''),
         string_agg(distinct ct_gov_id, ', ') filter (where coalesce(ct_gov_id, '') <> '')
    into n_nct, nct_ids
    from pc_op_research where ('|' || coalesce(knumbers, '') || '|') like '%|' || kn || '|%' and coalesce(ortho, true);
  c_ev := jsonb_set(c_ev, '{ask}', to_jsonb(case when n_st > 0
             then 'Share the results of the ' || n_st || ' industry-funded stud' || case when n_st = 1 then 'y that names' else 'ies that name' end
                  || ' this product, including any not yet published.'
             else 'No industry-funded studies name this product. What clinical data supports it, or why is none needed beyond its predicates?' end));
  c_ev := c_ev || jsonb_build_object('asks', pc_asks(c_ev->>'ask',
             case when n_nct > 0 then 'Which of these studies have results posted on ClinicalTrials.gov (' || nct_ids || ')?' end,
             case when n_st > 0 then 'What clinical data exists for this device itself, as opposed to its predicates?' end));
  c_cat := c_cat || jsonb_build_object('asks', pc_asks(
             case when coalesce(skus, 0) > 0 then 'GUDID lists ' || pc_num(skus) || ' catalog items under this 510(k). Can you confirm the full part-number list we would load, and explain any part numbers not in GUDID?' end,
             c_cat->>'ask'));
  c_cat := jsonb_set(c_cat, '{ask}', c_cat->'asks'->0);

  -- 2. What is it cleared to treat?
  ind := pc_device_indications(kn);
  ifu_clean := pc_clean_ifu(ind->>'ifu_text');
  sim := case when ifu_clean is not null and pc_clean_ifu(ind->'predicate'->>'ifu_text') is not null
              then nullif(ind->>'similarity', '')::numeric end;
  c_ind := pc_card('indications', 'What is it cleared to treat?',
    case when not (ind->>'found')::boolean and is_new then 'Not on file yet'
         when not (ind->>'found')::boolean then 'Not on file'
         when ifu_clean is null then 'Couldn''t read cleanly'
         when sim is null then 'On file'
         when sim >= 0.9 then 'Same wording as predicate'
         when sim >= 0.6 then 'Close to predicate'
         else 'Differs from predicate' end,
    case when not (ind->>'found')::boolean then 'attention' else 'info' end,
    case when not (ind->>'found')::boolean and is_new then 'NOT FOUND: the Indications for Use are not on file yet. The clearance is ' || days_new || ' days old, and FDA may not have posted its summary when this data was built.'
         when not (ind->>'found')::boolean and is_denovo then 'NOT FOUND: De Novo decision summaries are not loaded yet. FDA''s De Novo database has the Indications for Use.'
         when not (ind->>'found')::boolean and not has_summary then 'NOT FOUND: FDA posted no 510(k) summary for this clearance, so its Indications for Use are not on file.'
         when not (ind->>'found')::boolean then 'NOT FOUND: the Indications for Use could not be read from the 510(k) summary. The summary PDF linked on this page has them.'
         when ifu_clean is null then 'The Indications for Use text in FDA''s PDF could not be read cleanly, so it is not quoted or compared here. The summary PDF linked on this page has them.'
         else 'Cleared for: ' || left(ifu_clean, 260) || case when length(ifu_clean) > 260 then '…' else '' end
              || case when sim is not null then ' The wording is ' || round(sim * 100) || '% similar to its primary predicate, '
                        || coalesce(ind->'predicate'->>'device_name', 'name not on file') || ' (' || (ind->'predicate'->>'knumber') || ').'
                      when ind->'predicate'->>'knumber' is not null then ' The primary predicate''s Indications for Use are not on file, so the two can''t be compared.'
                      else '' end end,
    'A device is cleared for specific uses. Use outside them is off-label and can change coverage, consent and liability.',
    case when not (ind->>'found')::boolean or ifu_clean is null then 'Can you provide the cleared Indications for Use for this 510(k)?'
         else 'Which of the cleared indications will our surgeons use it for, and is any planned use outside them?' end,
    'indications');
  c_ind := c_ind || jsonb_build_object('short', 'Indications',
    'headline', case when not (ind->>'found')::boolean then 'Indications not on file.' when ifu_clean is null then 'Indications not readable.' else 'Indications on file.' end,
    'figs', pc_figs(case when sim is not null then pc_fig(round(sim * 100) || '%', 'wording similarity to the primary predicate') end,
                    pc_fig(ind->'predicate'->>'knumber', 'primary predicate')),
    'asks', pc_asks(c_ind->>'ask',
      case when sim is not null and sim < 0.9 then 'The indications wording is ' || round(sim * 100) || '% similar to its primary predicate, '
           || (ind->'predicate'->>'knumber') || '. What changed, and what data supports any new use?' end));

  -- 3. Who sells it today?
  own := pc_device_owner(kn);
  -- a buyer outside the registry (Phoenix Brio, Montagu Private Equity) comes from a dated, sourced lineage row
  select l.parent, l.valid_from into ft_parent, ft_from
    from pc_vendor_lineage l
   where l.vendor_id = vend and l.valid_from is not null and l.valid_to is null and coalesce(l.reviewed, false)
     and l.relation ~* '(acquired by|sold to)' and not exists (select 1 from pc_vendors p where p.vendor_id = l.parent)
   order by l.valid_from desc limit 1;
  if ft_parent is not null and not coalesce((own->>'divested')::boolean, false)
     and coalesce(own->>'owner_vendor_id', '') = coalesce(own->>'filer_vendor_id', '')
     and nullif(dev->>'decision_date', '')::date < ft_from then
    own := own || jsonb_build_object('owner_vendor_id', 'external', 'owner_name', ft_parent,
      'explanation', pc_co(coalesce(own->>'filer', company)) || ' was acquired by ' || ft_parent || ' in ' || to_char(ft_from, 'FMMonth YYYY') || '.');
  end if;
  if not coalesce((own->>'divested')::boolean, false) and coalesce(own->>'owner_vendor_id', '') = coalesce(own->>'filer_vendor_id', '')
     and not pc_same_name(pc_co(own->>'filer'), own->>'owner_name') then
    own := own || jsonb_build_object('filer_vendor_id', 'renamed', 'explanation', pc_co(own->>'owner_name') || ' sells it today.');
  end if;
  -- an owner with more than one dated change (K2M: Stryker in 2018, VB Spine in 2025) gets the whole chain
  select string_agg(coalesce(p.display_name, l.parent) || ' in ' || to_char(l.valid_from, 'FMMonth YYYY'), ', then ' order by l.valid_from)
    into chain
    from pc_vendor_lineage l left join pc_vendors p on p.vendor_id = l.parent
   where l.vendor_id = (select p2.vendor_id from pc_portfolio_510k p2 where p2.knumber = kn) and l.parent <> l.vendor_id and l.valid_from is not null
     and l.relation ~* '(acquired by|merged into|became part of|owned by|sold to)'
   having count(*) >= 2;
  if chain is not null and not coalesce((own->>'divested')::boolean, false) then
    own := own || jsonb_build_object('explanation', pc_co(own->>'filer') || ' became part of ' || chain
      || case when position(lower(regexp_replace(coalesce(own->>'owner_name', ''), '\s*\(.*\)$', '')) in lower(chain)) = 0
              then ', which sells it as ' || (own->>'owner_name') else '' end || '.');
  end if;
  if not coalesce((own->>'divested')::boolean, false) and coalesce(own->>'owner_vendor_id', '') <> coalesce(own->>'filer_vendor_id', '')
     and exists (select 1 from pc_vendor_lineage l where l.vendor_id = own->>'filer_vendor_id' and l.parent = own->>'owner_vendor_id'
                 and l.relation ~* '(same company|renamed)') then
    own := own || jsonb_build_object('filer_vendor_id', own->>'owner_vendor_id');
  end if;
  c_own := pc_card('owner', 'Who sells it today?',
    case when coalesce((own->>'divested')::boolean, false) or coalesce(own->>'owner_vendor_id', '') <> coalesce(own->>'filer_vendor_id', '')
         then 'Now ' || coalesce(own->>'owner_name', 'NOT FOUND') else 'Same company' end,
    case when coalesce((own->>'divested')::boolean, false) then 'attention' else 'info' end,
    'FDA cleared it for ' || rtrim(pc_co(coalesce(own->>'filer', company)), '.') || '. '
      || case when coalesce((own->>'divested')::boolean, false) or coalesce(own->>'owner_vendor_id', '') <> coalesce(own->>'filer_vendor_id', '')
              then coalesce(own->>'explanation', 'It is now part of ' || coalesce(own->>'owner_name', 'NOT FOUND') || '.')
              else 'The same company, ' || coalesce(own->>'owner_name', company) || ', sells it today.' end,
    'The contract, pricing, instrument sets and rep coverage come from whoever owns the product line now.',
    case when coalesce((own->>'divested')::boolean, false) or coalesce(own->>'owner_vendor_id', '') <> coalesce(own->>'filer_vendor_id', '')
         then coalesce(own->>'owner_name', 'The new owner') || ' now sells this product line. Do our contract, pricing and instrument sets carry over, and who supports revisions of implants already in patients?'
         else 'Is any sale, spin-off or change in distribution planned for this product line?' end,
    'owner');
  c_own := c_own || jsonb_build_object('short', 'Owner', 'headline', c_own->>'badge' || '.',
    'figs', pc_figs(pc_fig(pc_fix_text(pc_co(coalesce(own->>'filer', company))), '510(k) holder at clearance'), pc_fig(pc_fix_text(pc_co(own->>'owner_name')), 'sells it today')),
    'asks', pc_asks(c_own->>'ask'));

  -- 9. Any recalls? (card from 04_recall_functions.sql, with a question about its predicates)
  if to_regclass('public.pc_recalls') is not null then
    c_rec := pc_recall_card_product(kn, company);
    select nullif(f->>'value', '')::int into pred_recalls from jsonb_array_elements(c_rec->'figs') f
      where f->>'label' = 'on its direct predicates';
    c_rec := c_rec || jsonb_build_object('asks', pc_asks(c_rec->>'ask',
      case when coalesce(pred_recalls, 0) > 0 then 'FDA lists ' || pred_recalls || ' recall event' || case when pred_recalls = 1 then '' else 's' end
           || ' on its direct predicates. Were those problems designed out of this device?' end));
  end if;

  -- 10. Any adverse events? (MAUDE, 09_maude_functions.sql)
  if to_regprocedure('pc_device_maude(text)') is not null then
    mau := pc_device_maude(kn);
    r5 := (mau->'last5'->>'reports')::int; d5 := (mau->'last5'->>'deaths')::int;
    i5 := (mau->'last5'->>'injuries')::int; m5 := (mau->'last5'->>'malfunctions')::int;
    o5 := coalesce(r5, 0) - coalesce(d5, 0) - coalesce(i5, 0) - coalesce(m5, 0);
    mau_first := nullif(mau->>'first_year', '')::int;
    c_ae := pc_card('adverse_events', 'Any adverse events?',
      case when not coalesce((mau->>'has_reports')::boolean, false) then 'None reported'
           when coalesce(r5, 0) = 0 then pc_num((mau->>'reports')::numeric) || ', none recent'
           else pc_num(r5) || ' in five years' end,
      case when coalesce(d5, 0) > 0 then 'attention' else 'info' end,
      case when not coalesce((mau->>'has_reports')::boolean, false)
             then 'No FDA adverse event report (MAUDE) names this 510(k) number.'
                  || case when coalesce((mau->'category'->>'clearances')::numeric, 0) = 0 then ''
                          when coalesce((mau->'category'->>'with_reports')::numeric, 0) = 0 then ' No clearance in product code ' || code || ' has reports.'
                          else ' In product code ' || code || ', ' || pc_num((mau->'category'->>'with_reports')::numeric) || ' of '
                               || pc_count((mau->'category'->>'clearances')::numeric, 'clearance has', 'clearances have') || ' reports.' end
           else pc_num((mau->>'reports')::numeric) || ' MAUDE reports name this 510(k)' || coalesce(' since ' || (mau->>'first_year'), '')
                || case when coalesce(r5, 0) > 0 then '; ' || pc_num(r5) || ' in the last five years (' || pc_count(d5, 'death', 'deaths') || ', ' || pc_count(i5, 'injury', 'injuries') || ', ' || pc_count(m5, 'malfunction', 'malfunctions')
                        || case when o5 > 0 then ', ' || pc_num(o5) || ' other or not stated' else '' end || ').' else ', none in the last five years.' end
                || case when mau_first < dec_year then ' Reports dated before the ' || dec_year || ' clearance likely cite this 510(k) number in error or for an earlier version.' else '' end
                || coalesce(' In product code ' || code || ', the median for clearances with recent reports is '
                            || pc_num((mau->'category'->>'median_last5_with_reports')::numeric) || '.', '') end,
      'A report is not proof that the device caused an event, and counts are not rates: widely used products get more reports. A report counts only when it names the 510(k) number.',
      case when coalesce(r5, 0) > 0
           then 'FDA received ' || pc_num(r5) || ' adverse event reports naming this product in the last five years (' || pc_count(d5, 'death', 'deaths') || ', ' || pc_count(i5, 'injury', 'injuries') || ', ' || pc_count(m5, 'malfunction', 'malfunctions') || '). What failure modes drive them, and what changed in response?'
           when coalesce((mau->>'has_reports')::boolean, false)
           then 'What drove the ' || pc_num((mau->>'reports')::numeric) || ' earlier adverse event reports, and were those issues resolved in the current design?'
           else 'No adverse event reports name this 510(k) number. Are complaints for this product reported to FDA under another 510(k)?' end,
      'maude');
    c_ae := c_ae || jsonb_build_object('short', 'Adverse events',
      'headline', case when not coalesce((mau->>'has_reports')::boolean, false) then 'No reports name it.'
                       else pc_num(coalesce(r5, 0)) || ' reports in five years.' end,
      'figs', pc_figs(pc_fig(pc_num(coalesce(r5, 0)), 'reports, last five years'),
                      case when coalesce(r5, 0) > 0 then pc_fig(pc_num(d5), 'deaths') end,
                      case when coalesce(r5, 0) > 0 then pc_fig(pc_num(i5), 'injuries') end,
                      case when coalesce(r5, 0) > 0 then pc_fig(pc_num(m5), 'malfunctions') end,
                      pc_fig(pc_num(coalesce((mau->>'reports')::numeric, 0)), 'reports, all years')));
    c_ae := c_ae || jsonb_build_object('asks', pc_asks(c_ae->>'ask'));
  end if;

  -- 11. What is the vendor's supplier record? (sites listing this 510(k), 10_supplier_functions.sql)
  if to_regprocedure('pc_device_supplier(text)') is not null then
    sup := pc_device_supplier(kn);
    select string_agg(x, ', ') into partners from (select jsonb_array_elements_text(sup->'partner_making') x limit 3) z;
    select string_agg(pc_country(x), ', ') into countries from jsonb_array_elements_text(sup->'countries_making') x where x <> 'US';
    select string_agg(x, ', ') into flagged from (select jsonb_array_elements_text(sup->'flagged_sites') x limit 3) z;
    wl5 := coalesce((sup->>'warning_letters_last5')::int, 0); oai5 := coalesce((sup->>'oai_last5')::int, 0);
    c_sup := pc_card('supplier', 'What is the vendor''s supplier record?',
      case when (sup->>'sites')::int = 0 and is_recent then 'No sites yet'
           when (sup->>'sites')::int = 0 then 'No sites on file'
           when (sup->>'warning_letters_last5')::int > 0 then (sup->>'warning_letters_last5') || ' warning letter' || case when (sup->>'warning_letters_last5')::int = 1 then '' else 's' end
           when (sup->>'oai_last5')::int > 0 then (sup->>'oai_last5') || ' OAI inspection' || case when (sup->>'oai_last5')::int = 1 then '' else 's' end
           else (sup->>'sites') || ' site' || case when (sup->>'sites')::int = 1 then '' else 's' end end,
      case when (sup->>'warning_letters_last5')::int > 0 or (sup->>'oai_last5')::int > 0 then 'attention' else 'info' end,
      case when (sup->>'sites')::int = 0 and is_recent then 'No FDA establishment registration lists this 510(k) number yet. Companies update their registrations each year, so clearances under a year old often show none.'
           when (sup->>'sites')::int = 0 then 'No FDA establishment registration lists this 510(k) number, so its manufacturing sites are not on file.'
           else (sup->>'sites') || ' FDA-registered site' || case when (sup->>'sites')::int = 1 then ' lists' else 's list' end || ' this 510(k): '
                || array_to_string(array_remove(array[
                     case when (sup->>'company_sites')::int > 0 then (sup->>'company_sites') || ' of the company''s own' end,
                     case when (sup->>'partner_sites')::int > 0 then (sup->>'partner_sites') || ' partner firm' || case when (sup->>'partner_sites')::int = 1 then '' else 's' end
                          || coalesce(' (makers or sterilizers: ' || partners || ')', '') end,
                     case when (sup->>'other_company_sites')::int > 0 then (sup->>'other_company_sites') || case when (sup->>'other_company_sites')::int = 1 then ' belongs' else ' belong' end || ' to another device company, usually because the product line changed hands' end], null), '; ')
                || '. ' || case when coalesce((sup->>'inspections_last5')::int, 0) = 0 and coalesce((sup->>'warning_letters_last5')::int, 0) = 0
                                  then 'FDA did not inspect these sites for devices in the last five years and issued no warning letters.'
                                when coalesce((sup->>'inspections_last5')::int, 0) = 0
                                  then 'FDA did not inspect these sites for devices in the last five years and issued '
                                       || pc_count((sup->>'warning_letters_last5')::int, 'warning letter', 'warning letters') || '.'
                                else 'In the last five years FDA inspected these sites '
                                     || pc_count((sup->>'inspections_last5')::int, 'time', 'times')
                                     || ' for devices (' || case when (sup->>'oai_last5')::int = 0 then 'none' else (sup->>'oai_last5') end || ' classified OAI) and issued '
                                     || case when (sup->>'warning_letters_last5')::int = 0 then 'no warning letters'
                                             else pc_count((sup->>'warning_letters_last5')::int, 'warning letter', 'warning letters') end || '.' end end,
      'Shows who makes and handles the product and what FDA found at those sites. An inspection result describes one visit to one site, not the product.',
      case when (sup->>'sites')::int = 0 then 'Which FDA-registered site makes this product, and what is its FEI number?'
           else 'Which site makes this product, and what is your backup if that site stops shipping?' end,
      'supplier');
    c_sup := c_sup || jsonb_build_object('short', 'Supplier record',
      'headline', case when (sup->>'sites')::int = 0 then 'No sites on file.' else pc_count((sup->>'sites')::int, 'registered site', 'registered sites') || '.' end,
      'figs', pc_figs(pc_fig(sup->>'sites', 'sites list this 510(k)'), pc_fig(sup->>'making_sites', 'make or sterilize it'),
                      pc_fig(sup->>'inspections_last5', 'device inspections, last five years'), pc_fig(sup->>'oai_last5', 'classified OAI'),
                      pc_fig(sup->>'warning_letters_last5', 'warning letters, last five years')),
      'asks', pc_asks(c_sup->>'ask',
        case when partners is not null then partners || case when jsonb_array_length(sup->'partner_making') = 1
               then ' makes or sterilizes this product for you. How much buffer stock do you hold if that partner stops shipping?'
               else ' make or sterilize this product for you. How much buffer stock do you hold if one of them stops shipping?' end end,
        case when countries is not null then 'This product is made at sites in ' || countries || '. How do you manage import holds, tariffs and shipping delays?' end,
        case when flagged is not null then 'FDA ' || case when wl5 > 0 and oai5 > 0 then 'issued a warning letter and classified an inspection OAI'
                                                          when wl5 > 0 then 'issued a warning letter' else 'classified an inspection OAI' end
             || ' at ' || pc_tc(flagged) || ' in the last five years. Which corrective actions are complete, and did any affect this product?' end));
  end if;

  -- 12. What does Medicare pay for procedures that use it? (08_procedure_functions.sql)
  if to_regprocedure('pc_device_procedures(text)') is not null then
    procs := coalesce(pc_device_procedures(kn)->'procedures', '[]'::jsonb);
    n_fam := jsonb_array_length(procs);
    select x->>'family_id', x->>'name', x->>'status', pc_family_score(x->>'family_id', dtext) > 0 into fam_id, fam_name, fam_status, fam_match
      from jsonb_array_elements(procs) x
     order by pc_family_score(x->>'family_id', dtext) desc, (x->>'flagship')::boolean desc nulls last, x->>'name' limit 1;
    -- Phase 3: when the name doesn't pick one family, try the cleared indications; use them only if one family scores highest
    if n_fam > 1 and not fam_match and ifu_clean is not null then
      select x->>'family_id', x->>'name', x->>'status' into fam_id2, fam_name2, fam_status2
        from jsonb_array_elements(procs) x
       where pc_family_score(x->>'family_id', lower(ifu_clean)) > 0
         and pc_family_score(x->>'family_id', lower(ifu_clean)) > all (
               select pc_family_score(y->>'family_id', lower(ifu_clean)) from jsonb_array_elements(procs) y where y->>'family_id' <> x->>'family_id')
       limit 1;
      if fam_id2 is not null then
        fam_id := fam_id2; fam_name := fam_name2; fam_status := fam_status2; fam_match := true; fam_from_ifu := true;
      end if;
    end if;
    if n_fam > 0 then
      fam_other := pc_family_conflict(array(select x->>'family_id' from jsonb_array_elements(procs) x), lower(coalesce(dev->>'device_name', '')));
    end if;
    if fam_other is not null then
      -- the name points to a procedure this code isn't mapped to, so show no payment rather than the wrong one
      select string_agg(lower(x->>'name'), ' and to ' order by x->>'name') into fam_list from jsonb_array_elements(procs) x;
      c_med := pc_card('medicare', 'What does Medicare pay for procedures that use it?',
        'No match for this use', 'info',
        'NOT FOUND: product code ' || code || ' is mapped to ' || fam_list || ', but this device''s name points to ' || fam_other
          || '. OrthoParity shows no payment here because the mapped procedures don''t fit this device. Outpatient and ASC payments are not shown here.',
        'The DRG payment is fixed per case, so the implant cost has to fit inside it. For this device, the right procedure family has to come from how your surgeons will use it.',
        'Which procedures will our surgeons use it in, and are they inpatient or outpatient?',
        'procedures')
        || jsonb_build_object('short', 'Medicare payment', 'headline', 'No match for this use.',
             'figs', '[]'::jsonb,
             'asks', pc_asks('Which procedures will our surgeons use it in, and are they inpatient or outpatient?'));
    elsif n_fam > 1 and not fam_match then
      -- the device's name and indications don't say which procedure, so show the mapped procedures instead of guessing one,
      -- narrowed to the owner's segment (a spine company's navigation system) when that leaves at least one
      seg_fams := case lower((select segment from pc_vendors where vendor_id = own->>'owner_vendor_id'))
                    when 'spine' then array['thoracolumbar_fusion', 'cervical_fusion', 'spine_surgery_no_fusion']
                    when 'recon' then array['hip_knee_replacement', 'revision_hip_knee', 'shoulder_elbow_replacement', 'hip_fracture_replacement']
                    when 'trauma' then array['hip_femur_fixation', 'lower_extremity_humerus', 'hip_fracture_replacement', 'upper_extremity_no_replacement', 'foot_soft_tissue']
                    when 'sports medicine' then array['knee_surgery_no_replacement', 'upper_extremity_no_replacement', 'foot_soft_tissue']
                    when 'foot & ankle' then array['foot_soft_tissue', 'lower_extremity_humerus']
                    when 'foot and ankle' then array['foot_soft_tissue', 'lower_extremity_humerus'] end;
      if seg_fams is not null and exists (select 1 from jsonb_array_elements(procs) x where x->>'family_id' = any(seg_fams))
         and exists (select 1 from jsonb_array_elements(procs) x where not (x->>'family_id' = any(seg_fams))) then
        procs := (select jsonb_agg(x) from jsonb_array_elements(procs) x where x->>'family_id' = any(seg_fams));
        n_fam := jsonb_array_length(procs);
      end if;
      select string_agg(lower(x->>'name'), '; ' order by x->>'name') into fam_list from jsonb_array_elements(procs) x;
      select count(*), min(medicare_pays), max(medicare_pays) into drg_n, drg_min, drg_max from pc_procedure_drg
       where family_id in (select x->>'family_id' from jsonb_array_elements(procs) x);
      select max(data_year) into data_yr from pc_procedures where family_id in (select x->>'family_id' from jsonb_array_elements(procs) x);
      c_med := pc_card('medicare', 'What does Medicare pay for procedures that use it?',
        'Varies by procedure', 'info',
        'Medicare inpatient hospital payments, ' || data_yr || '. Product code ' || code
          || case when n_fam = 1 then ' fits ' else ' fits ' || n_fam || ' procedure families' end
          || case when seg_fams is not null and n_fam < jsonb_array_length(coalesce(pc_device_procedures(kn)->'procedures', '[]'::jsonb))
                  then ' within ' || coalesce(company, 'the company') || '''s focus' else '' end
          || ', and neither this device''s name nor its cleared indications say which. If it''s used in '
          || case when n_fam = 1 then fam_list else 'one of them (' || fam_list || ')' end
          || ', Medicare paid ' || pc_pay_range(drg_min, drg_max) || ' on average per case across ' || drg_n || ' MS-DRGs. '
          || 'This pays for the whole stay and every implant in it, not this product alone. Outpatient and ASC payments are not shown here.',
        'The DRG payment is fixed per case, so the implant cost has to fit inside it with the room, the operating room and the nursing. Which DRG a case falls into depends on the procedure, approach and complications.',
        'Which procedures will our surgeons use it in, and what will the full implant construct cost per case in each?',
        'procedures')
        || jsonb_build_object('short', 'Medicare payment', 'headline', 'Varies by procedure.',
             'figs', pc_figs(pc_fig(pc_num(n_fam), 'procedure families'), pc_fig(pc_usd(round(drg_min)), 'lowest DRG average'),
                             pc_fig(pc_usd(round(drg_max)), 'highest DRG average')),
             'asks', pc_asks('Which procedures will our surgeons use it in, and what will the full implant construct cost per case in each?'));
    end if;
    select count(*), min(medicare_pays), max(medicare_pays) into drg_n, drg_min, drg_max from pc_procedure_drg where family_id = fam_id;
    select medicare_pays, discharges, supply_total_30, supply_total_50, data_year into fam_avg, fam_dis, sup30, sup50, data_yr
      from pc_procedures where family_id = fam_id;
    if c_med is null then
    c_med := pc_card('medicare', 'What does Medicare pay for procedures that use it?',
      case when fam_id is null then 'No procedure match' else pc_pay_range(drg_min, drg_max, true) || ' per inpatient case' end,
      'info',
      case when fam_id is null and code is null then 'NOT FOUND: FDA''s record for this clearance lists no product code, so it can''t be mapped to a Medicare procedure family.'
           when fam_id is null then 'NOT FOUND: product code ' || code || ' is not mapped to a Medicare procedure family.'
           else 'Medicare inpatient hospital payments, ' || data_yr || '. Used in ' || lower(fam_name)
                || case when fam_from_ifu then ' (picked from its cleared indications; product code ' || code || ' also fits other procedures)' else '' end || ': ' || drg_n || ' MS-DRG' || case when drg_n = 1 then '' else 's' end || ', '
                || pc_num(fam_dis) || ' Medicare discharges in ' || data_yr || '. Medicare paid ' || pc_pay_range(drg_min, drg_max)
                || ' on average per case' || case when drg_n > 1 then ', depending on the DRG (' || pc_usd(round(fam_avg)) || ' across the family)' else '' end || '. '
                || 'This pays for the whole stay and every implant in it, not this product alone.'
                || case when fam_id = 'thoracolumbar_fusion' and code in ('OUR', 'SCY', 'QSR') then ' Inpatient sacroiliac joint fusion groups to MS-DRGs 459 and 460 within this family.' else '' end
                || case when fam_id = 'hip_knee_replacement' and dtext ~ 'ankle' then ' CMS groups total ankle replacement into these same DRGs, so the family figures mix hip, knee and ankle cases.' else '' end
                || case when sup30 is not null then ' Published cost studies put all implants at 30% to 50% of the case payment, about '
                          || pc_usd(round(sup30)) || ' to ' || pc_usd(round(sup50)) || '.' else '' end
                || case when n_fam > 1 then ' It is also mapped to ' || (n_fam - 1) || ' other procedure famil' || case when n_fam = 2 then 'y.' else 'ies.' end else '' end
                || ' The link from product code ' || code || ' to this procedure is ' || coalesce(fam_status, 'draft') || '.'
                || ' Outpatient and ASC payments are not shown here.' end,
      'The DRG payment is fixed per case, so the implant cost has to fit inside it with the room, the operating room and the nursing. Which DRG a case falls into depends on the approach, levels and complications.',
      case when fam_id is null then 'Which inpatient and outpatient procedures is this product used in?'
           else 'Medicare pays ' || pc_pay_range(drg_min, drg_max) || ' per case for ' || lower(fam_name)
                || '. What will the full implant construct cost per case at our volume?' end,
      'procedures');
    c_med := c_med || jsonb_build_object('short', 'Medicare payment',
      'headline', case when fam_id is null then 'No procedure match.' else pc_money(round(fam_avg)) || ' average per case.' end,
      'figs', pc_figs(pc_fig(pc_num(drg_n), 'MS-DRGs in ' || coalesce(lower(fam_name), 'the family')),
                      pc_fig(pc_usd(round(drg_min)), 'lowest DRG average'), pc_fig(pc_usd(round(drg_max)), 'highest DRG average'),
                      pc_fig(pc_num(fam_dis), 'Medicare discharges, ' || coalesce(data_yr::text, '')),
                      pc_fig(fam_status, 'mapping status')),
      'asks', pc_asks(c_med->>'ask',
        case when fam_id is not null then 'Which other implants complete the construct in a typical ' || lower(fam_name) || ' case, and are they on the same contract?' end));
    end if;
  end if;

  -- 13. Any Medicare add-on payments? (11_add_on_functions.sql)
  if to_regprocedure('pc_device_add_on(text)') is not null then
    addon := pc_device_add_on(kn);
    select max((x->>'max_payment')::numeric) filter (where x->>'program' = 'NTAP' and x->>'status' <> 'discontinued'),
           (array_agg(x->>'technology') filter (where x->>'program' = 'NTAP' and x->>'status' <> 'discontinued'))[1],
           string_agg(x->>'hcpcs', ', ') filter (where x->>'program' = 'TPT')
      into ntap_amt, ntap_name, tpt_code from jsonb_array_elements(addon->'items') x;
    select string_agg(distinct x->>'technology', '; ') into cat_tech from jsonb_array_elements(addon->'category') x;
    c_add := pc_card('add_on', 'Any Medicare add-on payments?',
      case when ntap_amt is not null and tpt_code is not null then 'NTAP and pass-through'
           when ntap_amt is not null then 'NTAP up to ' || pc_money(ntap_amt)
           when tpt_code is not null then 'Pass-through ' || tpt_code
           when jsonb_array_length(addon->'items') > 0 then 'NTAP ended'
           else 'None' end,
      'info',
      case when jsonb_array_length(addon->'items') = 0
             then 'No current Medicare add-on payment names this product line: no FY 2027 inpatient NTAP and no CY 2027 outpatient pass-through code.'
                  || coalesce(' In product code ' || code || ': ' || cat_tech || '.', '')
           else (select string_agg(case when x->>'program' = 'NTAP' then
                   x->>'technology' || ': inpatient NTAP, ' || case x->>'status' when 'new' then 'new for FY 2027' when 'continued' then 'continues in FY 2027' else 'ended for FY 2027' end
                   || ', up to ' || pc_usd(round((x->>'max_payment')::numeric)) || ' per inpatient case.'
                 else x->>'technology' || ': outpatient pass-through, HCPCS ' || (x->>'hcpcs')
                   || case when x->>'pass_through_ends' = 'during CY 2027' then ', expires during 2027.' else ', continues in CY 2027.' end end, ' ')
                 from jsonb_array_elements(addon->'items') x) end,
      'Medicare pays the hospital or ASC extra for a limited time when a qualifying new technology is used. It is a payment rule for Original Medicare, not a clinical endorsement or a price.',
      case when ntap_amt is not null then 'Medicare adds up to ' || pc_usd(round(ntap_amt)) || ' per inpatient case for this product in FY 2027. Do you provide coding guidance for the ICD-10-PCS codes CMS requires, and when does the add-on end?'
           when tpt_code is not null then 'Outpatient claims can bill HCPCS ' || tpt_code || ' for pass-through payment. Do you provide billing guidance for hospital outpatient departments and ASCs?'
           when cat_tech is not null then cat_tech || case when cat_tech like '%;%' then ' have Medicare add-on payments' else ' has a Medicare add-on payment' end
                || ' in the same product code. How does your product compare on total cost to the hospital?'
           else 'Is an NTAP or outpatient pass-through application planned for this product?' end,
      'addon');
    c_add := c_add || jsonb_build_object('short', 'Add-on payments',
      'headline', case when jsonb_array_length(addon->'items') = 0 then 'No add-on payment.' else c_add->>'badge' || '.' end,
      'figs', pc_figs(case when ntap_amt is not null then pc_fig(pc_usd(round(ntap_amt)), 'most NTAP per inpatient case, FY 2027') end,
                      case when tpt_code is not null then pc_fig(tpt_code, 'outpatient pass-through code, CY 2027') end,
                      pc_fig(pc_num(jsonb_array_length(addon->'category')), 'others in product code ' || coalesce(code, ''))),
      'asks', pc_asks(c_add->>'ask',
        case when ntap_amt is not null and tpt_code is not null then 'Outpatient claims can also bill HCPCS ' || tpt_code || ' for pass-through payment. Do you provide billing guidance for that too?' end));
  end if;
  cards := pc_figs(c_nov, c_ind, c_own, c_alt, c_pay, c_ev, c_cat, c_rec, c_ae, c_sup, c_med, c_add);

  if ntap_amt is not null then
    addon_lead := 'Medicare grants a new-technology add-on payment for it (NTAP, up to ' || pc_money(ntap_amt) || ' per inpatient case in FY 2027). ';
  elsif tpt_code is not null then
    addon_lead := 'Medicare grants an outpatient pass-through payment for it (HCPCS ' || tpt_code || ' in CY 2027). ';
  end if;
  bl := addon_lead || case when is_label then 'A labeling update, such as MR safety conditions, for a device already on the market. ' else '' end || case pattern
          when 'line extension' then 'A line extension of ' || company || '''s own product line'
          when 'competitive entry' then 'A competitive entry against ' || coalesce(others, 'other companies'' devices')
          when 'mixed' then 'Builds on ' || company || '''s own devices and other companies'''
          else case when is_denovo then 'A De Novo device, FDA''s first of its kind,'
                    when is_new then 'A new clearance whose predicates are not posted yet,'
                    when not has_summary then 'A clearance with no 510(k) summary on file,'
                    else 'A clearance with no predicate on file' end end
        || case when n_alt >= 20 then ' in a crowded product code (' || n_alt || ' other companies in five years). '
                when n_alt >= 5 then ' in a competitive product code (' || n_alt || ' other companies in five years). '
                when n_alt >= 1 then ' in a product code with few alternatives (' || n_alt || ' other compan' || case when n_alt = 1 then 'y' else 'ies' end || ' in five years). '
                else ' in a product code with no other recent clearances. ' end
        || case when coalesce(roy, 0) > 0 and brand_only then 'Royalties are paid on its brand. '
                when coalesce(roy, 0) > 0 then 'Royalties are paid on it. '
                when coalesce(tot, 0) > 0 and brand_only then 'Industry payments name its brand. '
                when coalesce(tot, 0) > 0 then 'Industry payments name it. ' else '' end
        || case when coalesce(n_st, 0) = 0 then 'No industry-funded studies name it.' else n_st || ' industry-funded stud' || case when n_st = 1 then 'y names' else 'ies name' end || ' it.' end;
  bl := pc_fix_text(bl);
  cards := (select jsonb_agg(pc_fix_card(c) order by o) from jsonb_array_elements(cards) with ordinality t(c, o));

  return jsonb_build_object(
    'found', true, 'knumber', kn,
    'header', jsonb_build_object('device_name', dev->>'device_name', 'company', company, 'owner', owner_name,
                                 'plain_name', plain, 'fda_name', pcode->>'fda_name', 'product_code', code,
                                 'cleared', dev->>'decision_date', 'device_class', dev->>'device_class',
                                 'procedures', pcode->>'procedures', 'anatomy', pcode->>'anatomy', 'kind', pcode->>'kind',
                                 'summary_url', dev->>'summary_url', 'pattern', pattern,
                                 'days_since_clearance', days_new, 'new_clearance', is_new),
    'bottom_line', bl, 'cards', cards,
    'alternatives', jsonb_build_object('window', 'Clearances after ' || to_char(data_end - interval '5 years', 'Mon DD, YYYY'),
                                       'companies', n_alt, 'rows', alts),
    'notes', jsonb_build_array(
      'Signals come from fixed rules on public FDA and CMS data. They frame questions and are not a judgment of the device or the company.',
      'Alternatives group companies by current owner and count clearances in the same FDA product code. A product code is broad, so not every alternative is a direct substitute.',
      'Catalog counts are the GUDID device IDs that cite this 510(k). A system sold under several 510(k)s spreads its items across them.')
      || case when is_new then jsonb_build_array('This clearance is ' || days_new || ' days old. GUDID listings, establishment registrations and the 510(k) summary often appear weeks or months after FDA clears a device.') else '[]'::jsonb end);
end $$;

create or replace function pc_vendor_signals(v text, m text default 'pit')
returns jsonb language plpgsql stable as $$
declare
  md text := pc_mode(m);
  ven pc_vendors;
  data_end date;
  n_cl int; n_codes int; n_active int; n_top3 int; top3_names text;
  v_last5 int; v_prior5 int; trend text;
  acq jsonb; n_acq int; acq_names text; acquired_by text; acquired_on date;
  latest int; tot double precision; recips int; cons_r int; roy_share double precision; max_holders int;
  n_st int; st_amt double precision; st_last int;
  n_brands int; n_disc int; disc_names text; n_devs int; cat_brands boolean;
  comp jsonb; cards jsonb; bl text; breadth text;
  c_rec jsonb; c_ae jsonb; c_sup jsonb; c_med jsonb; c_add jsonb; mau jsonb; sup jsonb; vaddon jsonb; vprocs jsonb;
  top_fam text; top_name text; n_fam int; drg_min numeric; drg_max numeric; data_yr int; rec5 int;
  r5 int; d5 int; i5 int; m5 int; top_prod text; countries text; n_nct int; first_yr int;
  top_unamb int; fam_list text; insp5 int;
begin
  select * into ven from pc_vendors where vendor_id = v;
  if ven.vendor_id is null then return jsonb_build_object('found', false, 'vendor_id', v); end if;
  data_end := pc_data_end();

  -- where they compete: every product code in the portfolio, ranked against other companies in the last five years
  with fam as (select vendor_id from pc_vendor_family(v, md) where md = 'current' or vendor_id = v),
  allp as (
    select p.product_code, p.decision_date,
           case when p.vendor_id in (select vendor_id from fam) then v
                when md = 'current' then coalesce(nullif(x.rolls_up_to, ''), x.vendor_id)
                else x.vendor_id end as grp
    from pc_portfolio_510k p join pc_vendors x on x.vendor_id = p.vendor_id
    where p.product_code in (select distinct product_code from pc_portfolio_510k where vendor_id in (select vendor_id from fam))),
  per as (
    select product_code, grp, count(*) as all_time,
           count(*) filter (where decision_date > data_end - interval '5 years') as last5
    from allp group by 1, 2),
  ranked as (
    select per.*, sum(last5) over (partition by product_code) as code_last5,
           count(*) filter (where last5 > 0) over (partition by product_code) as active_cos,
           case when last5 > 0 then rank() over (partition by product_code order by last5 desc) end as rnk
    from per)
  select coalesce(jsonb_agg(jsonb_build_object(
           'product_code', r.product_code, 'plain_name', c.plain_name, 'fda_name', c.fda_name, 'anatomy', c.anatomy, 'kind', c.kind,
           'clearances', r.all_time, 'last5', r.last5, 'code_last5', r.code_last5,
           'share_last5_pct', round((100.0 * r.last5 / nullif(r.code_last5, 0))::numeric, 1),
           'rank_last5', r.rnk, 'competitors_last5', r.active_cos - case when r.last5 > 0 then 1 else 0 end,
           'position', case when r.last5 = 0 then 'No recent clearances'
                            when r.rnk <= 3 and r.last5::numeric / nullif(r.code_last5, 0) >= 0.1 then 'Top 3'
                            else 'Active' end)
           order by r.last5 desc, r.all_time desc), '[]'::jsonb),
         sum(r.all_time), count(*), count(*) filter (where r.last5 > 0),
         count(*) filter (where r.rnk <= 3 and r.last5::numeric / nullif(r.code_last5, 0) >= 0.1),
         array_to_string((array_agg(coalesce(c.plain_name, c.fda_name, r.product_code) order by r.last5 desc)
                          filter (where r.rnk <= 3 and r.last5::numeric / nullif(r.code_last5, 0) >= 0.1))[1:3], '; ')
    into comp, n_cl, n_codes, n_active, n_top3, top3_names
    from ranked r left join pc_product_codes c on c.product_code = r.product_code
    where r.grp = v;

  -- all clearances, including the few with no product code on record
  select count(*) into n_cl from pc_portfolio_510k
    where vendor_id in (select vendor_id from pc_vendor_family(v, md) where md = 'current' or vendor_id = v);

  -- momentum
  select count(*) filter (where decision_date > data_end - interval '5 years'),
         count(*) filter (where decision_date <= data_end - interval '5 years' and decision_date > data_end - interval '10 years')
    into v_last5, v_prior5
    from pc_portfolio_510k where vendor_id in (select vendor_id from pc_vendor_family(v, md) where md = 'current' or vendor_id = v);
  trend := case when v_prior5 = 0 and v_last5 > 0 then 'New entrant'
                when v_last5 = 0 then 'No recent clearances'
                when v_last5 + v_prior5 < 5 then 'Too few to call a trend'
                when v_last5 >= 1.2 * v_prior5 then 'More recent clearances'
                when v_last5 <= 0.8 * v_prior5 then 'Fewer recent clearances'
                else 'Steady' end;

  -- ownership changes
  select coalesce(jsonb_agg(jsonb_build_object('vendor_id', l.vendor_id, 'name', c.display_name, 'date', l.valid_from,
                                               'relation', l.relation, 'source_url', l.source_url) order by l.valid_from desc), '[]'::jsonb),
         count(*) filter (where l.valid_from > current_date - interval '5 years'),
         string_agg(case when l.relation ~* '(assets|business|lines?)\M'
                         then c.display_name || '''s ' || btrim(regexp_replace(l.relation, '\s*(acquired by|sold to).*$', '', 'i'))
                         else c.display_name end
                    || ' (' || to_char(l.valid_from, 'Mon YYYY') || ')', ', ' order by l.valid_from desc)
           filter (where l.valid_from > current_date - interval '5 years')
    into acq, n_acq, acq_names
    from pc_vendor_lineage l join pc_vendors c on c.vendor_id = l.vendor_id
    where l.parent = v and l.vendor_id <> v
      and l.relation !~* '(subsidiary|same company|renamed|separation planned)';
  -- current owner, if another company: the latest open-ended ownership change (buyers need not be vendors;
  -- product-line sales and planned separations don't count)
  select coalesce(p.display_name, l.parent), l.valid_from into acquired_by, acquired_on
    from pc_vendor_lineage l left join pc_vendors p on p.vendor_id = l.parent
    where l.vendor_id = v and l.parent <> v and l.valid_to is null
      and l.relation ~* '(acquired by|merged into|owned by|sold to|spun off|became part of)'
      and l.relation !~* '(business sold|planned)' and coalesce(l.note, '') !~* 'history note'
    order by l.valid_from desc nulls last limit 1;

  -- payments
  select max(year) into latest from pc_op_vendor_profile where vendor_id = v and mode = md and year > 0;
  select total, recipients, consulting_r into tot, recips, cons_r from pc_op_vendor_profile where vendor_id = v and mode = md and year = latest;
  select sum(amount) filter (where nature_group = 'royalty') / nullif(sum(amount), 0) into roy_share
    from pc_op_vendor_year where vendor_id = v and mode = md;
  select max(h) into max_holders from (select year, sum(holders) h from pc_op_ownership o
    where (md = 'pit' and o.vendor_pit = v) or (md = 'current' and o.vendor_current = v) group by year) s;

  -- evidence
  select count(distinct study_name), sum(amount), max(year) into n_st, st_amt, st_last
    from pc_op_research r
    where ((md = 'pit' and r.vendor_pit = v) or (md = 'current' and r.vendor_current = v)) and coalesce(r.ortho, true);

  -- supply
  select count(*), count(*) filter (where devices > 0 and in_distribution = 0),
         array_to_string((array_agg(brand order by devices desc, brand) filter (where devices > 0 and in_distribution = 0))[1:5], ', '),
         sum(devices)
    into n_brands, n_disc, disc_names, n_devs
    from pc_portfolio_brands where vendor_id in (select vendor_id from pc_vendor_family(v, md) where md = 'current' or vendor_id = v);

  -- some companies type catalog descriptions (sizes, sides, trials) into GUDID's brand field, which inflates "brands"
  cat_brands := coalesce(n_brands, 0) >= 200 and n_brands >= 0.2 * coalesce(n_devs, 0);

  breadth := case when n_codes >= 12 and coalesce(n_active, 0) <= 2 then 'Broad but inactive'
                  when n_codes >= 12 then 'Broad portfolio' when n_codes <= 3 then 'Focused' else 'Moderate breadth' end;

  cards := jsonb_build_array(
    pc_card('breadth', 'Where do they compete?', breadth, 'info',
      coalesce(pc_num(n_cl), '0') || ' orthopedic 510(k)' || case when n_cl = 1 then '' else 's' end || ' across ' || coalesce(n_codes, 0)
        || ' product code' || case when n_codes = 1 then '' else 's' end || ', with clearances in '
        || coalesce(n_active, 0) || ' of them in the last five years.'
        || case when n_top3 = 1 then ' A top-3 filer in one category: ' || lower(top3_names) || '.'
                when n_top3 > 1 then ' A top-3 filer in ' || n_top3 || ' categories, including ' || lower(top3_names) || '.' else '' end,
      case when breadth = 'Broad but inactive' then 'Many product lines on record but few new clearances. Confirm which lines are still supported.'
           when n_codes >= 12 then 'A broad portfolio makes a portfolio or bundled agreement possible.'
           when n_codes <= 3 then 'A specialist. Compare it category by category rather than as a portfolio.'
           else 'Large enough to bundle a few categories, focused enough to compare category by category.' end,
      case when n_codes >= 12 then 'Which categories would you include in a portfolio agreement, and what pricing applies if we consolidate?'
           else 'Where is your portfolio headed in the next two years?' end,
      'competition'),
    pc_card('momentum', 'Are they still investing?', trend,
      case when trend = 'No recent clearances' then 'attention' else 'info' end,
      case when coalesce(v_last5, 0) = 0 and coalesce(v_prior5, 0) = 0 then 'No orthopedic clearances in the last ten years of data.'
           else pc_count(coalesce(v_last5, 0), 'orthopedic clearance', 'orthopedic clearances') || ' in the last five years of data, versus '
                || coalesce(v_prior5, 0) || ' in the five years before.' end,
      case trend when 'More recent clearances' then 'The company is adding new and updated products faster than before.'
                 when 'Fewer recent clearances' then 'Fewer new clearances can reflect a maturing portfolio or fewer, larger projects. Roadmap and long-term support are worth confirming.'
                 when 'No recent clearances' then 'No new clearances in five years. Long-term support and revision parts matter more.'
                 when 'New entrant' then 'A newer company in orthopedics. Supply capacity and field support matter more.'
                 when 'Too few to call a trend' then 'With so few clearances, the change between the two periods doesn''t mean much.'
                 else 'A steady pace of new and updated products.' end,
      'What is launching in the next 12 months, and what is being retired?',
      'portfolio'),
    pc_card('ownership', 'Have any acquisitions or mergers occurred?',
      case when acquired_by is not null then 'Acquired' when n_acq > 0 then 'Recent acquisitions'
           when jsonb_array_length(acq) > 0 then 'No recent changes' else 'No changes on record' end,
      case when acquired_by is not null or n_acq > 0 then 'attention' else 'info' end,
      case when acquired_by is not null then 'Acquired by ' || acquired_by || coalesce(' on ' || to_char(acquired_on, 'Mon DD, YYYY'), '') || '.'
           when n_acq > 0 then 'Acquired ' || acq_names || '.'
           when jsonb_array_length(acq) > 0 then 'No acquisitions or ownership changes in the last five years. Earlier on record: '
                || (select string_agg((x->>'name') || coalesce(' (' || to_char((x->>'date')::date, 'Mon YYYY') || ')', ''), ', ')
                      from jsonb_array_elements(acq) x) || '.'
           else 'No acquisitions or ownership changes in OrthoParity''s reviewed registry.' end,
      case when acquired_by is not null or n_acq > 0 then 'Acquisitions consolidate product lines. Contract pricing, instrument sets and rep coverage can change.'
           else 'The registry covers major orthopedic deals since 2018, so smaller transactions may be missing.' end,
      case when acquired_by is not null or n_acq > 0 then 'Which product lines will continue, and how will pricing, instrument sets and rep coverage change?'
           else 'Are any ownership or financing changes planned that could affect supply or support?' end,
      'ownership'),
    pc_card('payments', 'What are the financial ties for this vendor?',
      case when coalesce(tot, 0) = 0 then 'None in scope' when roy_share > 0.5 then 'Royalty-led' when coalesce(roy_share, 0) < 0.05 then 'No royalties' else 'Mixed' end, 'info',
      case when coalesce(tot, 0) > 0 then
             pc_money(tot) || ' in reported payments in ' || latest || coalesce(' to ' || to_char(recips, 'FM999,999,999') || ' recipients', '') || '. Royalties are '
             || round((100 * coalesce(roy_share, 0))::numeric) || '% of payments since 2019'
             || case when coalesce(cons_r, 0) > 0 then '; ' || cons_r || ' consultants were paid in ' || latest else '' end
             || case when coalesce(max_holders, 0) > 0 then '; up to ' || max_holders || ' physicians a year reported ownership' else '' end || '.'
           else 'No orthopedic-scope Open Payments records for this vendor from 2019 to 2025.' end,
      'Royalties go mostly to inventors and design surgeons; consulting goes to surgeons who advise, train or develop products. These relationships are normal in device development, and committees track them for disclosure.',
      'Will you disclose every financial relationship you have with our surgeons, as our conflict-of-interest policy requires?',
      'payments'),
    pc_card('evidence', 'Are they building clinical evidence?',
      case when coalesce(n_st, 0) > 0 then n_st || ' industry-funded' else 'None in Open Payments' end,
      'info',
      case when coalesce(n_st, 0) > 0 then pc_money(st_amt) || ' in industry-funded orthopedic research across ' || n_st || ' studies since 2019, latest in ' || st_last || '.'
           else 'No industry-funded orthopedic research in Open Payments from 2019 to 2025.' end,
      case when coalesce(n_st, 0) > 0 then 'Shows where the company is building evidence. Results matter more than spend.'
           else 'Evidence may come from predicate devices, published literature or studies outside Open Payments.' end,
      'Which studies cover the products you are proposing, and when will results be published?',
      'research'),
    pc_card('supply', 'Is the portfolio in distribution?',
      case when coalesce(n_disc, 0) > 0 then n_disc || ' brand' || case when n_disc = 1 then '' else 's' end || ' discontinued' else 'All in distribution' end,
      case when coalesce(n_disc, 0) > 0 then 'attention' else 'info' end,
      case when coalesce(n_disc, 0) > 0 then pc_num(n_disc) || ' of ' || pc_num(n_brands) || ' orthopedic brands in GUDID list no devices in commercial distribution'
                                              || coalesce(' (' || disc_names || ')', '') || '.'
           else 'Every orthopedic brand in GUDID lists devices in commercial distribution.' end
        || case when cat_brands then ' This company fills GUDID''s brand field with catalog descriptions (sizes, sides, trials), so '
                  || pc_num(n_brands) || ' brand entries cover ' || pc_num(n_devs) || ' devices and overstate its product lines.' else '' end,
      'Discontinued lines can strand instrument sets and leave revision patients without parts.',
      'Is every line you are proposing in full distribution, and what is your end-of-life policy for revision parts?',
      'brands'));
  cards := jsonb_set(cards, '{0,headline}', to_jsonb(coalesce(n_codes, 0) || ' product code' || case when n_codes = 1 then '.' else 's.' end));
  cards := jsonb_set(cards, '{1,headline}', to_jsonb(coalesce(v_last5, 0) || ' clearance' || case when v_last5 = 1 then '' else 's' end || ' in five years.'));
  cards := jsonb_set(cards, '{2,headline}', to_jsonb(case when acquired_by is not null then 'Now part of ' || acquired_by || '.'
                                                        when n_acq > 0 then 'Recent acquisitions.'
                                                        when jsonb_array_length(acq) > 0 then 'No recent ownership changes.'
                                                        else 'No ownership changes on record.' end));
  cards := jsonb_set(cards, '{3,headline}', to_jsonb(case when coalesce(tot, 0) > 0 then pc_money(tot) || ' in ' || latest || '.'
                                                        else 'No payments in scope.' end));
  cards := jsonb_set(cards, '{4,headline}', to_jsonb(case when coalesce(n_st, 0) > 0 then n_st || case when n_st = 1 then ' study' else ' studies' end || ' since 2019.'
                                                        else 'No studies reported.' end));
  cards := jsonb_set(cards, '{5,headline}', to_jsonb(case when coalesce(n_disc, 0) > 0 then n_disc || ' brand' || case when n_disc = 1 then '' else 's' end || ' discontinued.'
                                                        else 'All brands in distribution.' end));
  cards := jsonb_set(cards, '{0}', (cards->0) || jsonb_build_object('short', 'Competition', 'figs', pc_figs(
             pc_fig(pc_num(n_codes), 'product codes'), pc_fig(pc_num(n_active), 'with clearances in the last five years'),
             pc_fig(pc_num(n_top3), 'categories as a top-3 filer'))));
  cards := jsonb_set(cards, '{1}', (cards->1) || jsonb_build_object('short', 'Investment', 'figs', pc_figs(
             pc_fig(pc_num(v_last5), 'clearances, last five years'), pc_fig(pc_num(v_prior5), 'the five years before'))));
  cards := jsonb_set(cards, '{2}', (cards->2) || jsonb_build_object('short', 'Acquisitions', 'figs', pc_figs(
             pc_fig(pc_num(n_acq), case when n_acq = 1 then 'acquisition, last five years' else 'acquisitions, last five years' end),
             pc_fig(pc_num(jsonb_array_length(acq)), case when jsonb_array_length(acq) = 1 then 'acquisition on record, all years' else 'acquisitions on record, all years' end),
             case when acquired_by is not null then pc_fig(to_char(acquired_on, 'YYYY'), 'acquired by ' || acquired_by) end)));
  cards := jsonb_set(cards, '{3}', (cards->3) || jsonb_build_object('short', 'Financial ties', 'figs', case when coalesce(tot, 0) > 0 then pc_figs(
             pc_fig(pc_money(tot), 'reported payments in ' || latest), pc_fig(pc_num(recips), 'recipients in ' || latest),
             pc_fig(round((100 * coalesce(roy_share, 0))::numeric) || '%', 'royalties since 2019'),
             case when coalesce(cons_r, 0) > 0 then pc_fig(pc_num(cons_r), 'consultants paid in ' || latest) end)
           else pc_figs(pc_fig('0', 'orthopedic-scope payments, 2019 to 2025')) end));
  cards := jsonb_set(cards, '{4}', (cards->4) || jsonb_build_object('short', 'Evidence', 'figs', pc_figs(
             case when n_st > 0 then pc_fig(pc_money(st_amt), 'industry-funded research since 2019') end,
             pc_fig(pc_num(coalesce(n_st, 0)), 'industry-funded studies'), case when n_st > 0 then pc_fig(st_last::text, 'latest year') end)));
  cards := jsonb_set(cards, '{5}', (cards->5) || jsonb_build_object('short', 'Distribution', 'figs', pc_figs(
             pc_fig(pc_num(coalesce(n_disc, 0)), 'brands with no devices in distribution'), pc_fig(pc_num(n_brands), case when cat_brands then 'GUDID brand entries (catalog-level)' else 'orthopedic brands in GUDID' end))));
  -- questions for the six cards above (the first is each card's ask)
  first_yr := ven.first_clearance_year;
  if to_regprocedure('pc_vendor_procedures(text,text)') is not null then
    vprocs := coalesce(pc_vendor_procedures(v, md)->'procedures', '[]'::jsonb);
    n_fam := jsonb_array_length(vprocs);
    -- each product counts toward the procedure its own name points to (or its code's only procedure); products
    -- whose name and code can't say which procedure (navigation, plates, screws) don't count
    with prods as (
      select p.knumber, p.product_code, lower(coalesce(p.device_name, '') || ' ' || coalesce(c.plain_name, '')) as dt, lower(coalesce(p.device_name, '')) as dn
        from pc_portfolio_510k p left join pc_product_codes c on c.product_code = p.product_code
       where p.vendor_id in (select vendor_id from pc_vendor_family(v, md) where md = 'current' or vendor_id = v)),
    cand as (
      select pr.knumber, pd.family_id, pc_family_score(pd.family_id, pr.dt) as sc, count(*) over (partition by pr.knumber) as nf,
             pc_family_conflict(array(select x.family_id from pc_procedure_devices x where x.product_code = pr.product_code), pr.dn) as conflict
        from prods pr join pc_procedure_devices pd on pd.product_code = pr.product_code),
    best as (select distinct on (knumber) knumber, family_id, sc, nf from cand where conflict is null order by knumber, sc desc, family_id)
    select b.family_id, f.name, count(*) into top_fam, top_name, top_unamb
      from best b join pc_procedures f on f.family_id = b.family_id
     where b.sc > 0 or b.nf = 1
     group by 1, 2 order by 3 desc, 2 limit 1;
    if n_fam > 1 and coalesce(top_unamb, 0) = 0 then
      select string_agg(lower(x->>'name'), '; ' order by x->>'name') into fam_list from jsonb_array_elements(vprocs) x;
    end if;
  end if;
  select count(distinct ct_gov_id) filter (where coalesce(ct_gov_id, '') <> '') into n_nct from pc_op_research r
    where ((md = 'pit' and r.vendor_pit = v) or (md = 'current' and r.vendor_current = v)) and coalesce(r.ortho, true);
  cards := jsonb_set(cards, '{0,asks}', pc_asks(cards->0->>'ask',
             case when top_name is not null then 'In ' || lower(top_name) || ', which of your products make a complete construct, and which parts would we buy from another vendor?' end,
             case when first_yr >= extract(year from data_end)::int - 10 then 'You filed your first orthopedic 510(k) in ' || first_yr || '. How will you guarantee supply, instrument sets and field support as our volume grows?' end));
  cards := jsonb_set(cards, '{1,asks}', pc_asks(cards->1->>'ask',
             case when trend in ('Fewer recent clearances', 'No recent clearances') then 'Which product lines are you no longer developing, and how long will you support implants and instruments for them?' end));
  cards := jsonb_set(cards, '{2,asks}', pc_asks(cards->2->>'ask'));
  cards := jsonb_set(cards, '{3,asks}', pc_asks(cards->3->>'ask',
             'How do you set surgeon consulting and royalty rates?',
             case when coalesce(tot, 0) > 0 then 'Explain the ' || pc_money(tot) || ' in ' || latest || ' payments: how much was royalties, consulting, education, travel and meals?' end));
  cards := jsonb_set(cards, '{4,asks}', pc_asks(cards->4->>'ask',
             case when coalesce(n_nct, 0) > 0 then n_nct || ' of your funded studies have ClinicalTrials.gov numbers. Which have results posted, and can you share any that are not yet published?' end));
  cards := jsonb_set(cards, '{5,asks}', pc_asks(cards->5->>'ask'));

  -- Any recalls? (04_recall_functions.sql)
  if to_regclass('public.pc_recalls') is not null then
    c_rec := pc_recall_card_vendor(v, md) || jsonb_build_object('question', 'Any recalls?', 'short', 'Recalls');
    select nullif(f->>'value', '')::int into rec5 from jsonb_array_elements(c_rec->'figs') f where f->>'label' = 'recall events, last five years';
    c_rec := c_rec || jsonb_build_object('asks', pc_asks(c_rec->>'ask',
      case when coalesce(rec5, 0) > 0 then 'Explain the ' || rec5 || ' recall event' || case when rec5 = 1 then '' else 's' end
           || ' in the last five years: what caused ' || case when rec5 = 1 then 'it' else 'them' end || ', and what changed in design, manufacturing or labeling?' end));
  end if;

  -- Any adverse events? (09_maude_functions.sql)
  if to_regprocedure('pc_vendor_maude(text,text,integer)') is not null then
    mau := pc_vendor_maude(v, md, 3);
    r5 := (mau->'last5'->>'reports')::int; d5 := (mau->'last5'->>'deaths')::int;
    i5 := (mau->'last5'->>'injuries')::int; m5 := (mau->'last5'->>'malfunctions')::int;
    top_prod := pc_short_name(mau->'top_products'->0->>'device_name');
    c_ae := pc_card('adverse_events', 'Any adverse events?',
      case when coalesce((mau->>'reports')::int, 0) = 0 then 'None reported' when coalesce(r5, 0) = 0 then 'None in five years' else pc_num(coalesce(r5, 0)) || ' in five years' end,
      case when coalesce(d5, 0) > 0 then 'attention' else 'info' end,
      case when coalesce((mau->>'reports')::int, 0) = 0 then 'No FDA adverse event report (MAUDE) names any of this company''s orthopedic 510(k)s.'
           else pc_num((mau->>'reports')::numeric) || ' MAUDE reports name ' || pc_num((mau->>'products_with_reports')::numeric) || ' of its '
                || pc_num((mau->>'products')::numeric) || ' orthopedic 510(k)s; ' || pc_num(coalesce(r5, 0)) || ' in the last five years ('
                || pc_count(d5, 'death', 'deaths') || ', ' || pc_count(i5, 'injury', 'injuries') || ', ' || pc_count(m5, 'malfunction', 'malfunctions') || ')'
                || coalesce(', most for ' || top_prod, '') || '.' end,
      'A report is not proof that a device caused an event, and counts are not rates: companies with more products in use get more reports. A report counts only when it names the 510(k) number.',
      case when coalesce(r5, 0) > 0 then 'FDA received ' || pc_num(r5) || ' adverse event reports naming your 510(k)s in the last five years ('
                || pc_count(d5, 'death', 'deaths') || ', ' || pc_count(i5, 'injury', 'injuries') || ', ' || pc_count(m5, 'malfunction', 'malfunctions') || ')'
                || coalesce(', most for ' || top_prod, '') || '. What failure modes drive them, and what changed in response?'
           else 'How do you report complaints to FDA, and under which 510(k) numbers?' end,
      'maude');
    c_ae := c_ae || jsonb_build_object('short', 'Adverse events',
      'headline', case when coalesce((mau->>'reports')::int, 0) = 0 then 'No reports name its 510(k)s.' else pc_num(coalesce(r5, 0)) || ' reports in five years.' end,
      'figs', pc_figs(pc_fig(pc_num(coalesce(r5, 0)), 'reports, last five years'),
                      case when coalesce(r5, 0) > 0 then pc_fig(pc_num(d5), 'deaths') end,
                      case when coalesce(r5, 0) > 0 then pc_fig(pc_num(i5), 'injuries') end,
                      case when coalesce(r5, 0) > 0 then pc_fig(pc_num(m5), 'malfunctions') end,
                      pc_fig(pc_num(coalesce((mau->>'products_with_reports')::numeric, 0)), '510(k)s with reports')),
      'asks', pc_asks(case when coalesce(r5, 0) > 0 then 'FDA received ' || pc_num(r5) || ' adverse event reports naming your 510(k)s in the last five years ('
                || pc_count(d5, 'death', 'deaths') || ', ' || pc_count(i5, 'injury', 'injuries') || ', ' || pc_count(m5, 'malfunction', 'malfunctions') || ')'
                || coalesce(', most for ' || top_prod, '') || '. What failure modes drive them, and what changed in response?'
           else 'How do you report complaints to FDA, and under which 510(k) numbers?' end,
        'How do you share complaint and adverse event trends with hospital customers?'));
  end if;

  -- What is the vendor's supplier record? (10_supplier_functions.sql)
  if to_regprocedure('pc_vendor_supplier(text,text)') is not null then
    sup := pc_vendor_supplier(v, md);
    select string_agg(pc_country(x->>'country'), ', ') into countries
      from jsonb_array_elements(sup->'countries') x where x->>'country' not in ('US', '');
    insp5 := coalesce((sup->'inspections_last5'->>'inspections')::int, 0);
    c_sup := pc_card('supplier', 'What is the vendor''s supplier record?',
      case when (sup->'warning_letters'->>'company_last5')::int > 0 then (sup->'warning_letters'->>'company_last5') || ' warning letter'
                || case when (sup->'warning_letters'->>'company_last5')::int = 1 then '' else 's' end || ' in five years'
           when (sup->'inspections_last5'->>'oai')::int > 0 then (sup->'inspections_last5'->>'oai') || ' OAI inspection'
                || case when (sup->'inspections_last5'->>'oai')::int = 1 then '' else 's' end || ' in five years'
           when (sup->'sites'->>'company_sites')::int = 0 then 'No company sites on file'
           else pc_count((sup->'sites'->>'company_sites')::numeric, 'company site', 'company sites') end,
      case when (sup->'warning_letters'->>'company_last5')::int > 0 or (sup->'inspections_last5'->>'oai')::int > 0 then 'attention' else 'info' end,
      case when (sup->'sites'->>'company_sites')::int = 0 and (sup->'sites'->>'partner_sites')::int = 0
             then 'No FDA establishment registration lists this company''s orthopedic 510(k)s, so its sites are not on file.'
           else (sup->'sites'->>'company_sites') || ' company site' || case when (sup->'sites'->>'company_sites')::int = 1 then '' else 's' end
                || case when coalesce((sup->'sites'->>'company_making')::int, 0) = 0 then ' (none listed as a manufacturer)'
                        else ' (' || (sup->'sites'->>'company_making') || case when (sup->'sites'->>'company_making')::int = 1 then ' makes' else ' make' end || ' devices)' end
                || ' in ' || (sup->'sites'->>'company_countries') || ' countr'
                || case when (sup->'sites'->>'company_countries')::int = 1 then 'y' else 'ies' end
                || case when (sup->'sites'->>'partner_sites')::int > 0 then ', plus ' || (sup->'sites'->>'partner_sites') || ' partner site'
                        || case when (sup->'sites'->>'partner_sites')::int = 1 then '' else 's' end else '' end
                || case when insp5 = 0 then '. FDA did not inspect company sites for devices in the last five years. '
                        else '. In the last five years FDA inspected company sites ' || insp5 || ' time'
                || case when insp5 = 1 then '' else 's' end || ' for devices ('
                || (sup->'inspections_last5'->>'nai') || ' NAI, ' || (sup->'inspections_last5'->>'vai') || ' VAI, ' || (sup->'inspections_last5'->>'oai')
                || ' OAI). ' end || case when (sup->'warning_letters'->>'company_all')::int = 0 then 'FDA has issued no device warning letters to company sites since fiscal 2009.'
                   else pc_count((sup->'warning_letters'->>'company_last5')::numeric, 'warning letter', 'warning letters') || ' in the last five years, '
                        || (sup->'warning_letters'->>'company_all') || ' since fiscal 2009.' end end,
      'Shows where the company makes its products and what FDA found there. An inspection result describes one visit to one site, not the company''s products.',
      'Which sites make the products you are proposing, and what is your backup if one stops shipping?',
      'supplier');
    c_sup := c_sup || jsonb_build_object('short', 'Supplier record',
      'headline', c_sup->>'badge' || '.',
      'figs', pc_figs(pc_fig(sup->'sites'->>'company_sites', 'company sites'), pc_fig(sup->'sites'->>'company_countries', 'countries'),
                      pc_fig(sup->'inspections_last5'->>'inspections', 'device inspections, last five years'),
                      pc_fig(sup->'inspections_last5'->>'oai', 'classified OAI'),
                      pc_fig(sup->'warning_letters'->>'company_last5', 'warning letters, last five years'),
                      pc_fig(sup->'sites'->>'partner_sites', 'partner sites')),
      'asks', pc_asks(c_sup->>'ask',
        case when (sup->'warning_letters'->>'company_last5')::int > 0 or (sup->'inspections_last5'->>'oai')::int > 0
             then 'FDA issued ' || (sup->'warning_letters'->>'company_last5') || ' warning letter' || case when (sup->'warning_letters'->>'company_last5')::int = 1 then '' else 's' end
                  || ' and classified ' || (sup->'inspections_last5'->>'oai') || ' inspection' || case when (sup->'inspections_last5'->>'oai')::int = 1 then '' else 's' end
                  || ' OAI at your sites in the last five years. Which corrective actions are complete, and did any affect products you are proposing?' end,
        case when (sup->'sites'->>'partner_making')::int > 0 then 'Which contract manufacturers and sterilizers make the products you are proposing, and do you have a second source for each?' end,
        case when countries is not null then 'Your products are made at sites in ' || countries || '. How do you manage tariffs, import holds and shipping delays?' end));
  end if;

  -- What does Medicare pay for procedures that use their products? (08_procedure_functions.sql)
  if vprocs is not null and fam_list is not null then
    select min(medicare_pays), max(medicare_pays) into drg_min, drg_max from pc_procedure_drg
     where family_id in (select x->>'family_id' from jsonb_array_elements(vprocs) x);
    select max(data_year) into data_yr from pc_procedures where family_id in (select x->>'family_id' from jsonb_array_elements(vprocs) x);
    c_med := pc_card('medicare', 'What does Medicare pay for procedures that use their products?', 'Varies by procedure', 'info',
      'Its products map to ' || n_fam || ' Medicare procedure families, and their product codes are shared across procedures, so no single one stands out: '
        || fam_list || '. Medicare paid ' || pc_pay_range(drg_min, drg_max) || ' on average per inpatient case across them in ' || data_yr
        || '. That pays for the whole stay and every implant in it.',
      'The procedure payment is fixed per case, so implant cost has to fit inside it.',
      'Which procedures are your products used in at our facility, and what will they cost per case in each?',
      'procedures')
      || jsonb_build_object('short', 'Medicare payment', 'headline', 'Varies by procedure.',
           'figs', pc_figs(pc_fig(pc_num(n_fam), 'procedure families'), pc_fig(pc_usd(round(drg_min)), 'lowest DRG average'),
                           pc_fig(pc_usd(round(drg_max)), 'highest DRG average')),
           'asks', pc_asks('Which procedures are your products used in at our facility, and what will they cost per case in each?'));
  elsif vprocs is not null then
    select min(medicare_pays), max(medicare_pays) into drg_min, drg_max from pc_procedure_drg where family_id = top_fam;
    select data_year into data_yr from pc_procedures where family_id = top_fam;
    c_med := pc_card('medicare', 'What does Medicare pay for procedures that use their products?',
      case when top_fam is null then 'No procedure match' else pc_pay_range(drg_min, drg_max, true) || ' per inpatient case' end,
      'info',
      case when top_fam is null then 'NOT FOUND: none of this company''s product codes is mapped to a Medicare procedure family.'
           else 'Its products map to ' || n_fam || ' Medicare procedure famil' || case when n_fam = 1 then 'y' else 'ies' end
                || '. The family with most of its products is ' || lower(top_name) || ', where Medicare paid ' || pc_pay_range(drg_min, drg_max)
                || ' on average per case in ' || data_yr || '. That pays for the whole stay and every implant in it.' end,
      'The procedure payment is fixed per case, so implant cost has to fit inside it. Product-code-to-procedure links are reviewed by hand; see the procedure section for each family''s status.',
      case when top_fam is null then 'Which inpatient and outpatient procedures are your products used in?'
           else 'Medicare pays ' || pc_pay_range(drg_min, drg_max) || ' per case for ' || lower(top_name)
                || '. What will your implants cost per case for the constructs you are proposing?' end,
      'procedures');
    c_med := c_med || jsonb_build_object('short', 'Medicare payment',
      'headline', case when top_fam is null then 'No procedure match.' else c_med->>'badge' || '.' end,
      'figs', pc_figs(pc_fig(pc_num(n_fam), 'procedure families'), pc_fig(pc_usd(round(drg_min)), 'lowest DRG average, ' || coalesce(lower(top_name), '')),
                      pc_fig(pc_usd(round(drg_max)), 'highest DRG average')),
      'asks', pc_asks(c_med->>'ask'));
  end if;

  -- Any Medicare add-on payments? (11_add_on_functions.sql)
  if to_regprocedure('pc_vendor_add_on(text,text)') is not null then
    vaddon := pc_vendor_add_on(v, md);
    c_add := pc_card('add_on', 'Any Medicare add-on payments?',
      case when jsonb_array_length(vaddon->'items') = 0 then 'None'
           else array_to_string(array_remove(array[
                  case when (vaddon->>'ntap')::int > 0 then (vaddon->>'ntap') || ' NTAP' end,
                  case when (vaddon->>'pass_through')::int > 0 then (vaddon->>'pass_through') || ' pass-through' end], null), ', ')
                || case when (vaddon->>'ntap')::int = 0 and (vaddon->>'pass_through')::int = 0 then 'NTAP ended' else '' end end,
      'info',
      case when jsonb_array_length(vaddon->'items') = 0
             then 'None of this company''s technologies has a current Medicare add-on payment (FY 2027 inpatient NTAP or CY 2027 outpatient pass-through).'
           else (select string_agg(x->>'technology' || case when x->>'program' = 'NTAP'
                   then ' (NTAP, ' || case x->>'status' when 'discontinued' then 'ended for FY 2027' else 'up to ' || pc_usd(round((x->>'max_payment')::numeric)) || ' per inpatient case' end || ')'
                   else ' (pass-through ' || (x->>'hcpcs') || ')' end, '; ') from jsonb_array_elements(vaddon->'items') x) || '.' end,
      'Medicare pays the hospital or ASC extra for a limited time when a qualifying new technology is used. It is a payment rule for Original Medicare, not a clinical endorsement or a price.',
      case when jsonb_array_length(vaddon->'items') > 0 then 'Which of the products you are proposing carry a Medicare add-on payment, and do you provide coding and billing guidance for them?'
           else 'Do you plan NTAP or outpatient pass-through applications for any product you are proposing?' end,
      'addon');
    c_add := c_add || jsonb_build_object('short', 'Add-on payments',
      'headline', case when jsonb_array_length(vaddon->'items') = 0 then 'No add-on payments.' else c_add->>'badge' || '.' end,
      'figs', pc_figs(pc_fig(vaddon->>'ntap', 'inpatient NTAP, FY 2027'), pc_fig(vaddon->>'pass_through', 'outpatient pass-through codes, CY 2027')),
      'asks', pc_asks(c_add->>'ask'));
  end if;
  cards := cards || pc_figs(c_rec, c_ae, c_sup, c_med, c_add);

  bl := ven.display_name || ': ' || lower(breadth) || ' (' || coalesce(n_codes, 0) || ' product code' || case when n_codes = 1 then '' else 's' end
        || case when n_top3 > 0 then ', a top-3 filer in ' || n_top3 || ' categor' || case when n_top3 = 1 then 'y' else 'ies' end else '' end || '), '
        || case trend when 'More recent clearances' then 'more clearances than the five years before'
                      when 'Fewer recent clearances' then 'fewer clearances than the five years before'
                      when 'Steady' then 'a steady clearance pace'
                      when 'New entrant' then 'a new entrant' when 'Too few to call a trend' then 'too few clearances to call a trend'
                      else 'no recent clearances' end
        || case when acquired_by is not null then ', now part of ' || acquired_by
                when n_acq > 0 then ', with recent acquisitions' else '' end
        || '. ' || case when coalesce(tot, 0) = 0 then 'No orthopedic-scope payments on record.'
                        when roy_share > 0.5 then 'Payments are royalty-led.'
                        when coalesce(roy_share, 0) < 0.05 then 'Payments are consulting, education and travel, with almost no royalties.'
                        else 'Payments are a mix of royalties and field engagement.' end;
  -- Phase 3: a company with no orthopedic 510(k)s of its own (Integra after its orthopedics sale, names that appear only in
  -- GUDID or Open Payments) gets a page that says so instead of "focused (0 product codes)"
  if coalesce(n_cl, 0) > 0 and coalesce(n_codes, 0) = 0 then
    bl := replace(bl, '(0 product codes)', '(no product code on FDA''s record)');
  end if;
  if coalesce(n_cl, 0) = 0 then
    bl := ven.display_name || ': no orthopedic 510(k)s on file under this company'
          || case when coalesce(n_brands, 0) > 0 or coalesce(tot, 0) > 0
                  then '. It has a page because ' || array_to_string(array_remove(array[
                         case when coalesce(n_brands, 0) > 0 then 'GUDID lists ' || pc_count(n_brands, 'orthopedic brand', 'orthopedic brands') || ' under it' end,
                         case when coalesce(tot, 0) > 0 then 'Open Payments lists ' || pc_money(tot) || ' in ' || latest end], null), ' and ')
                  else '. Its name appears in FDA records that OrthoParity links to orthopedic devices' end || '.';
    cards := jsonb_set(cards, '{0}', (cards->0) || jsonb_build_object('badge', 'No 510(k)s on file', 'headline', 'No orthopedic 510(k)s on file.',
               'finding', 'No orthopedic 510(k) on file lists this company as the applicant, and no company that rolls up to it has one either.'));
    cards := jsonb_set(cards, '{1}', (cards->1) || jsonb_build_object('badge', 'No 510(k)s on file', 'headline', 'No orthopedic 510(k)s on file.',
               'finding', 'No orthopedic 510(k)s on file, so there is no clearance trend to show.'));
  end if;

  bl := pc_fix_text(bl);
  cards := (select jsonb_agg(pc_fix_card(c) order by o) from jsonb_array_elements(cards) with ordinality t(c, o));
  return jsonb_build_object(
    'found', true, 'mode', md, 'vendor', to_jsonb(ven), 'bottom_line', bl, 'cards', cards,
    'competition', comp, 'acquisitions', acq,
    'notes', jsonb_build_array(
      'Signals come from fixed rules on public FDA and CMS data. They frame questions and are not a judgment of the company.',
      'Rank and share count 510(k) clearances in each product code over the last five years of data, by company. Clearances measure product activity, not sales.',
      'Research is limited to studies in orthopedic scope by rule; some broad research programs may still include non-orthopedic work.'));
end $$;

grant execute on function pc_fig(text, text), pc_num(numeric), pc_figs(jsonb[]), pc_money(double precision), pc_data_end(), pc_card(text, text, text, text, text, text, text, text),
  pc_signals(text), pc_vendor_signals(text, text), pc_tc(text), pc_initcap(text), pc_fix_text(text), pc_fix_card(jsonb), pc_same_name(text, text),
  pc_clean_ifu(text), pc_family_score(text, text), pc_family_conflict(text[], text) to anon, authenticated;
