-- A change of face value moves the traded price by the whole ratio, a one for five split by
-- eighty percent. Adjustment exists to remove that step, so on the continuous series the day
-- either side of a succession must move no more than an ordinary day does. A step surviving
-- here means a momentum factor reads a split as a crash. A change reviewed and listed in
-- unadjusted_changes_of_isin, whose step no venue's record explains, is passed over.

-- The largest move, in log terms, an ordinary day makes. Price bands hold a smaller company to 20
-- percent a day, and trading after a split often carries it to the band's edge, 0.18 in log terms.
-- A missed split of one for two or larger moves 0.69.
{% set ordinary_move = 0.25 %}
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
where
    abs(ln(close_on / close_before)) > {{ ordinary_move }}
    and not exists (
        select 1 from {{ ref('unadjusted_changes_of_isin') }} as reviewed
        where
            reviewed.successor_isin = either_side.successor_isin
            and reviewed.changed_on = either_side.changed_on
    )
