{{ config(meta = {'dagster': {'ref': {'name': 'venue_delivery_discrepancies'}}}) }}

-- A reviewed venue day inside the stored history must be a day the venue traded, dated as
-- stg_trading_day dates it, or the delivery check passes over a day that is not there.
with held as (
    select
        venue,
        min(trade_date) as first_day,
        max(trade_date) as last_day
    from {{ ref('stg_trading_day') }}
    group by venue
)

select
    reviewed.venue,
    reviewed.trade_date
from {{ ref('venue_delivery_discrepancies') }} as reviewed
inner join held
    on reviewed.venue = held.venue
where
    reviewed.trade_date between held.first_day and held.last_day
    and not exists (
        select 1 from {{ ref('stg_trading_day') }} as days
        where
            days.venue = reviewed.venue
            and days.trade_date = reviewed.trade_date
    )
