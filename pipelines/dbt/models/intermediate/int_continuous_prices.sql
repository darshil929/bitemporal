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

capital_actions as (
    select distinct
        lineage.current_isin,
        actions.action_type,
        actions.ex_date,
        actions.qualifier,
        actions.adjustment_factor
    from {{ ref('stg_corporate_actions') }} as actions
    inner join lineage on actions.isin = lineage.isin
    where
        actions.action_type in ('split', 'bonus', 'consolidation')
        and actions.adjustment_factor is not null
),

-- Two actions can share an ex-date, a bonus beside a split, and both scale the same bars.
by_ex_date as (
    select
        current_isin,
        ex_date,
        exp(sum(ln(adjustment_factor))) as day_factor
    from capital_actions
    group by current_isin, ex_date
),

-- The factor a bar carries is the product of every action still ahead of it, so the running
-- product is accumulated backwards from the most recent action.
steps as (
    select
        current_isin,
        ex_date,
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
left join lateral (
    select steps.factor
    from steps
    where
        steps.current_isin = bars.current_isin
        and steps.ex_date > bars.trade_date
    order by steps.ex_date asc
    limit 1
) as applicable on true
