-- The venue each instrument's newest feature row was computed on, which a page opens on.
select
    instruments.isin,
    newest.primary_venue,
    newest.trade_date,
    newest.as_of_date
from {{ ref('mart_instruments') }} as instruments
cross join lateral (
    select
        features.primary_venue,
        features.trade_date,
        features.as_of_date
    from {{ source('features', 'mart_daily_features') }} as features
    where features.isin = instruments.isin
    order by features.trade_date desc
    limit 1
) as newest
