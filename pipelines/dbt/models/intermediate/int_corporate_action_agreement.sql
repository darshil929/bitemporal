-- Each day on which BSE or NSE reports a count-changing action for an instrument listed at both
-- venues, with the factor each venue's actions apply that day. BSE's actions scale the price series
-- and NSE's check them, so they are compared by the factor they apply together rather than one
-- action at a time, which a bonus and a split announced as one or as two would otherwise split.
with lineage as (
    select
        isin,
        current_isin
    from {{ ref('int_instrument_lineage') }}
),

capital_actions as (
    select distinct
        lineage.current_isin,
        actions.source_id,
        actions.action_type,
        actions.ex_date,
        actions.qualifier,
        actions.adjustment_factor,
        actions.as_of_date
    from {{ ref('stg_corporate_actions') }} as actions
    inner join lineage on actions.isin = lineage.isin
    where
        actions.action_type in ('split', 'bonus', 'consolidation')
        and actions.adjustment_factor is not null
),

by_day as (
    select
        current_isin,
        source_id,
        ex_date,
        max(as_of_date) as as_of_date,
        round(exp(sum(ln(adjustment_factor))), 10) as factor
    from capital_actions
    group by current_isin, source_id, ex_date
),

listed_on as (
    select
        lineage.current_isin,
        listings.exchange,
        listings.listing_date,
        listings.delisting_date
    from {{ ref('stg_listings') }} as listings
    inner join lineage on listings.isin = lineage.isin
),

days as (
    select distinct
        by_day.current_isin,
        by_day.ex_date
    from by_day
    where
        exists (
            select 1 from listed_on
            where
                listed_on.current_isin = by_day.current_isin
                and listed_on.exchange = 'BSE'
                and listed_on.listing_date <= by_day.ex_date
                and (listed_on.delisting_date is null or by_day.ex_date <= listed_on.delisting_date)
        )
        and exists (
            select 1 from listed_on
            where
                listed_on.current_isin = by_day.current_isin
                and listed_on.exchange = 'NSE'
                and listed_on.listing_date <= by_day.ex_date
                and (listed_on.delisting_date is null or by_day.ex_date <= listed_on.delisting_date)
        )
)

select
    days.current_isin as isin,
    days.ex_date,
    bse.factor as bse_factor,
    nse.factor as nse_factor,
    greatest(bse.as_of_date, nse.as_of_date) as as_of_date,
    case
        when bse.factor is null then 'nse_only'
        when nse.factor is null then 'bse_only'
        when bse.factor = nse.factor then 'agree'
        else 'differ'
    end as agreement
from days
left join by_day as bse
    on
        days.current_isin = bse.current_isin
        and days.ex_date = bse.ex_date
        and bse.source_id = 'bse_corporate_actions'
left join by_day as nse
    on
        days.current_isin = nse.current_isin
        and days.ex_date = nse.ex_date
        and nse.source_id = 'nse_corporate_actions'
