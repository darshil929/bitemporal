-- Each venue's own daily figures, computed as the daily features compute theirs, on the venue's
-- whole series and in the same order of operations, for every day the venue traded. Each figure
-- looks back along the series, so a read names its instruments.
with bars as (
    select
        isin,
        venue,
        trade_date,
        close_as_traded,
        max(as_of_date) over (
            partition by isin, venue
            order by trade_date asc
            rows between unbounded preceding and current row
        ) as bars_known,
        (close::float8 - lag(close::float8) over series)
        / adjustment_factor::float8 as change_1d,
        (close::float8 - lag(close::float8) over series)
        / lag(close::float8) over series as return_1d,
        (close::float8 - lag(close::float8, 21) over series)
        / lag(close::float8, 21) over series as return_1m,
        delivery_quantity::float8 / nullif(volume::float8, 0) * 100 as delivery_pct_1d
    from {{ ref('int_continuous_prices') }}
    window series as (partition by isin, venue order by trade_date asc)
),

-- The latest of the applied factors' knowable days, holding from each ex-date to the next.
actions as (
    select
        isin,
        ex_date,
        max(as_of_date) over (
            partition by isin
            order by ex_date asc
            rows between unbounded preceding and current row
        ) as actions_known,
        lead(ex_date) over (partition by isin order by ex_date asc) as next_ex_date
    from {{ ref('int_applied_action_dates') }}
)

select
    bars.isin,
    bars.venue,
    bars.trade_date,
    bars.close_as_traded as close,
    bars.change_1d,
    bars.return_1d,
    bars.return_1m,
    bars.delivery_pct_1d,
    greatest(bars.bars_known, actions.actions_known) as as_of_date
from bars
left join actions
    on
        bars.isin = actions.isin
        and bars.trade_date >= actions.ex_date
        and (actions.next_ex_date is null or bars.trade_date < actions.next_ex_date)
