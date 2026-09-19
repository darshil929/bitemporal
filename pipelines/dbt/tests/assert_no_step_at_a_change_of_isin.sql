-- A change of face value moves the traded price by the whole ratio, a one for five split by
-- eighty percent. Adjustment exists to remove that step, so on the continuous series the day
-- either side of a succession must move no more than an ordinary day does. A step surviving
-- here means a momentum factor reads a split as a crash.
with boundaries as (
    select
        successions.successor_isin,
        successions.changed_on,
        prices.venue,
        max(prices.trade_date) as last_day_before
    from {{ ref('stg_successions') }} as successions
    inner join {{ ref('int_continuous_prices') }} as prices
        on
            successions.successor_isin = prices.isin
            and successions.changed_on > prices.trade_date
    group by successions.successor_isin, successions.changed_on, prices.venue
),

either_side as (
    select
        boundaries.successor_isin,
        boundaries.venue,
        boundaries.changed_on,
        before.close as close_before,
        on_the_day.close as close_on
    from boundaries
    inner join {{ ref('int_continuous_prices') }} as before
        on
            boundaries.successor_isin = before.isin
            and boundaries.venue = before.venue
            and boundaries.last_day_before = before.trade_date
    inner join {{ ref('int_continuous_prices') }} as on_the_day
        on
            boundaries.successor_isin = on_the_day.isin
            and boundaries.venue = on_the_day.venue
            and boundaries.changed_on = on_the_day.trade_date
)

select
    successor_isin,
    venue,
    changed_on,
    close_before,
    close_on
from either_side
where abs(close_before / close_on - 1) > 0.10
