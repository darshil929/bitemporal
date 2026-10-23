{{ config(severity = 'warn', meta = {'dagster': {'ref': {'name': 'int_continuous_prices'}}}) }}

-- An applied split, bonus or consolidation scales every earlier price by its factor, so across its
-- ex-date the adjusted close moves no more than an ordinary day does. A step surviving here means
-- the prices show another factor than the one applied: terms the venue states that the shares did
-- not follow, or a further action the same day that no factor applies. Each venue is judged between
-- its last bar before the ex-date and its first on or after it, where those lie close enough
-- together for a move between them to be the action's. A day listed in reviewed_capital_actions is
-- passed over: its terms were judged against the venues' records and the prices, and a step left
-- there is one the review explains, such as a demerger the same day.

-- The largest move, in log terms, an ordinary day makes, as at a change of ISIN.
{% set ordinary_move = 0.25 %}
-- Bars further apart than this span a pause in trading, across which a price moves for reasons
-- of its own.
{% set judged_within_days = 7 %}
with applied as (
    select
        isin,
        ex_date,
        applied_factor
    from {{ ref('int_capital_action_factors') }}
    where applied_factor is not null and basis != 'reviewed'
),

either_side as (
    select
        applied.isin,
        applied.ex_date,
        applied.applied_factor,
        venues.venue,
        previous.trade_date as day_before,
        previous.close as close_before,
        on_the_day.trade_date as day_on,
        on_the_day.close as close_on
    from applied
    cross join (values ('BSE'), ('NSE')) as venues (venue)
    cross join
        lateral (
            select
                prices.trade_date,
                prices.close
            from {{ ref('int_continuous_prices') }} as prices
            where
                prices.isin = applied.isin
                and prices.venue = venues.venue
                and prices.trade_date < applied.ex_date
            order by prices.trade_date desc
            limit 1
        ) as previous
    cross join lateral (
        select
            prices.trade_date,
            prices.close
        from {{ ref('int_continuous_prices') }} as prices
        where
            prices.isin = applied.isin
            and prices.venue = venues.venue
            and prices.trade_date >= applied.ex_date
        order by prices.trade_date asc
        limit 1
    ) as on_the_day
)

select
    isin,
    ex_date,
    venue,
    applied_factor,
    day_before,
    close_before,
    day_on,
    close_on
from either_side
where
    day_on - day_before <= {{ judged_within_days }}
    and close_before > 0
    and close_on > 0
    and abs(ln(close_on / close_before)) > {{ ordinary_move }}
