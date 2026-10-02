-- The name each instrument is shown under: BSE's list, then NSE's, then either list's name for the
-- ISIN the instrument trades under now, then the name its venue's price file printed. BSE marks
-- some names with a trailing "-$", which is no part of the name.
with bse as (
    select
        isin,
        as_of_date,
        regexp_replace(name, '-\$$', '') as name
    from {{ ref('stg_instrument_names') }}
    where source_id = 'bse_scrip_list'
),

nse as (
    select
        isin,
        as_of_date,
        name
    from {{ ref('stg_instrument_names') }}
    where source_id = 'nse_equity_list'
)

select
    instruments.isin,
    coalesce(bse.name, nse.name, bse_now.name, nse_now.name, instruments.name) as display_name,
    case
        when bse.name is not null then 'bse_scrip_list'
        when nse.name is not null then 'nse_equity_list'
        when bse_now.name is not null then 'bse_scrip_list'
        when nse_now.name is not null then 'nse_equity_list'
        else 'price_file'
    end as named_by,
    case
        when
            coalesce(bse.name, nse.name) is null
            and coalesce(bse_now.name, nse_now.name) is not null
            then lineage.current_isin
        else instruments.isin
    end as named_isin,
    coalesce(bse.as_of_date, nse.as_of_date, bse_now.as_of_date, nse_now.as_of_date) as as_of_date
from {{ ref('stg_instruments') }} as instruments
inner join {{ ref('int_instrument_lineage') }} as lineage on instruments.isin = lineage.isin
left join bse on instruments.isin = bse.isin
left join nse on instruments.isin = nse.isin
left join bse as bse_now on lineage.current_isin = bse_now.isin
left join nse as nse_now on lineage.current_isin = nse_now.isin
