-- OrthoParity database: run after every CSV import
-- Part of the OrthoParity data pipeline (MIT License). Run the files in this folder in number order in the
-- Supabase SQL Editor (or psql). Every file is safe to run again. See supabase/README.md.

-- The dashboard importer can store empty cells as empty text; the functions expect NULL.
select pc_clean_blanks();

-- Mark which research payments are in orthopedic scope.
select pc_refresh_research_scope();

-- Row counts, to compare with outputs/site_data (one row per table).
select 'pc_devices' as table_name, count(*) as rows from pc_devices
union all select 'pc_edges', count(*) from pc_edges
union all select 'pc_flags', count(*) from pc_flags
union all select 'pc_meta', count(*) from pc_meta
union all select 'pc_product_codes', count(*) from pc_product_codes
union all select 'pc_ifu', count(*) from pc_ifu
union all select 'pc_vendors', count(*) from pc_vendors
union all select 'pc_vendor_names', count(*) from pc_vendor_names
union all select 'pc_vendor_lineage', count(*) from pc_vendor_lineage
union all select 'pc_portfolio_brands', count(*) from pc_portfolio_brands
union all select 'pc_portfolio_510k', count(*) from pc_portfolio_510k
union all select 'pc_op_vendor_year', count(*) from pc_op_vendor_year
union all select 'pc_op_vendor_profile', count(*) from pc_op_vendor_profile
union all select 'pc_op_entity', count(*) from pc_op_entity
union all select 'pc_op_product', count(*) from pc_op_product
union all select 'pc_op_product_top', count(*) from pc_op_product_top
union all select 'pc_op_research', count(*) from pc_op_research
union all select 'pc_op_relationship', count(*) from pc_op_relationship
union all select 'pc_op_ownership', count(*) from pc_op_ownership
union all select 'pc_recalls', count(*) from pc_recalls
order by 1;
