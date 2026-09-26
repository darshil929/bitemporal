-- One series per instrument that survives a change of face value, keyed on the ISIN the
-- instrument trades under now. A split issues a new ISIN carrying no earlier bars, so the
-- predecessor's bars are drawn in through the lineage and scaled by the actions that followed
-- them. Read this rather than stg_price_daily wherever a series must span a split. Delivery is
-- a count of shares like volume, so it is divided by the same factor.
with lineage as (
    select
        isin,
        current_isin
    from {{ ref('int_instrument_lineage') }}
),

-- Each ex-date's factor, BSE's where it reports one and NSE's where the prices confirm it.
by_ex_date as (
    select
        isin as current_isin,
        ex_date,
        applied_factor as day_factor
    from {{ ref('int_capital_action_factors') }}
    where applied_factor is not null
),

-- The factor a bar carries is the product of every action still ahead of it, so the running
-- product is accumulated backwards from the most recent action. It holds from the previous
-- ex-date up to the day before this one, which a bar is joined on as a range.
steps as (
    select
        current_isin,
        ex_date,
        lag(ex_date) over (partition by current_isin order by ex_date) as previous_ex_date,
        round(
            exp(
                sum(ln(day_factor)) over (
                    partition by current_isin
                    order by ex_date desc
                    rows between unbounded preceding and current row
                )
            ),
            10
        ) as factor
    from by_ex_date
),

bars as (
    select
        lineage.current_isin,
        prices.isin,
        prices.venue,
        prices.trade_date,
        prices.open,
        prices.high,
        prices.low,
        prices.close,
        prices.volume,
        delivery.delivery_quantity,
        greatest(prices.as_of_date, delivery.as_of_date) as as_of_date
    from {{ ref('stg_price_daily') }} as prices
    inner join lineage on prices.isin = lineage.isin
    left join {{ ref('stg_delivery_daily') }} as delivery
        on
            prices.isin = delivery.isin
            and prices.venue = delivery.venue
            and prices.trade_date = delivery.trade_date
)

select
    bars.current_isin as isin,
    bars.isin as source_isin,
    bars.venue,
    bars.trade_date,
    bars.as_of_date,
    bars.close as close_as_traded,
    coalesce(applicable.factor, 1) as adjustment_factor,
    round(bars.open * coalesce(applicable.factor, 1), 4) as open,
    round(bars.high * coalesce(applicable.factor, 1), 4) as high,
    round(bars.low * coalesce(applicable.factor, 1), 4) as low,
    round(bars.close * coalesce(applicable.factor, 1), 4) as close,
    round(bars.volume / coalesce(applicable.factor, 1)) as volume,
    round(bars.delivery_quantity / coalesce(applicable.factor, 1)) as delivery_quantity
from bars
left join steps as applicable
    on
        bars.current_isin = applicable.current_isin
        and bars.trade_date < applicable.ex_date
        and (applicable.previous_ex_date is null or bars.trade_date >= applicable.previous_ex_date)
