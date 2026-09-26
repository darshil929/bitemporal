-- The factor the continuous series applies on each day either venue reports a count-changing
-- action. Each venue misses actions the other records, and NSE has filed an action under the
-- wrong company, so neither is taken alone: BSE's actions stand, and a day NSE alone reports is
-- applied only where the close moved by its factor at every venue that traded either side of the
-- ex-date.

-- A venue's closes within this many days either side of the ex-date measure its move there. A
-- venue that did not trade on both sides within it is not counted.
{% set window_days = 10 %}

-- A move confirms a factor when it lies within this distance of it in log terms, and nearer to it
-- than to no action at all. A company held at a 20 percent circuit limit on its ex-date moves 0.18
-- from its factor.
{% set tolerance = 0.25 %}

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

-- A bonus and a split can share an ex-date, and both scale the same bars.
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

bse as (
    select * from by_day
    where source_id = 'bse_corporate_actions'
),

nse as (
    select * from by_day
    where source_id = 'nse_corporate_actions'
),

reported as (
    select
        bse.factor as bse_factor,
        nse.factor as nse_factor,
        bse.as_of_date as bse_as_of_date,
        nse.as_of_date as nse_as_of_date,
        coalesce(bse.current_isin, nse.current_isin) as current_isin,
        coalesce(bse.ex_date, nse.ex_date) as ex_date
    from bse
    full outer join nse
        on
            bse.current_isin = nse.current_isin
            and bse.ex_date = nse.ex_date
),

-- The close before and after a day NSE alone reports, at each venue, drawn across the lineage so
-- a split that issued a new ISIN is measured from the retired one to its successor.
moves as (
    select
        reported.current_isin,
        reported.ex_date,
        venues.venue,
        ln(after.close / before.close) as log_move,
        greatest(before.as_of_date, after.as_of_date) as as_of_date
    from reported
    cross join (values ('BSE'), ('NSE')) as venues (venue)
    inner join lateral (
        select
            prices.close,
            prices.as_of_date
        from {{ ref('stg_price_daily') }} as prices
        inner join lineage on prices.isin = lineage.isin
        where
            lineage.current_isin = reported.current_isin
            and prices.venue = venues.venue
            and prices.trade_date < reported.ex_date
            and prices.trade_date >= reported.ex_date - {{ window_days }}
        order by prices.trade_date desc
        limit 1
    ) as before on true
    inner join lateral (
        select
            prices.close,
            prices.as_of_date
        from {{ ref('stg_price_daily') }} as prices
        inner join lineage on prices.isin = lineage.isin
        where
            lineage.current_isin = reported.current_isin
            and prices.venue = venues.venue
            and prices.trade_date >= reported.ex_date
            and prices.trade_date < reported.ex_date + {{ window_days }}
        order by prices.trade_date asc
        limit 1
    ) as after on true
    where reported.bse_factor is null
),

evidence as (
    select
        moves.current_isin,
        moves.ex_date,
        count(*) as venues_traded,
        count(*) filter (
            where abs(moves.log_move - ln(reported.nse_factor))
            <= least({{ tolerance }}, abs(ln(reported.nse_factor)) / 2)
        ) as venues_confirming,
        max(moves.as_of_date) as as_of_date
    from moves
    inner join reported
        on
            moves.current_isin = reported.current_isin
            and moves.ex_date = reported.ex_date
    group by moves.current_isin, moves.ex_date
),

judged as (
    select
        reported.current_isin,
        reported.ex_date,
        reported.bse_factor,
        reported.nse_factor,
        coalesce(evidence.venues_traded, 0) as venues_traded,
        coalesce(evidence.venues_confirming, 0) as venues_confirming,
        case
            when reported.bse_factor is not null then 'bse'
            when evidence.venues_traded is null then 'nse_untraded'
            when evidence.venues_confirming = evidence.venues_traded then 'nse_confirmed'
            else 'nse_contradicted'
        end as basis,
        case
            when reported.bse_factor is not null then reported.bse_as_of_date
            else greatest(reported.nse_as_of_date, evidence.as_of_date)
        end as as_of_date
    from reported
    left join evidence
        on
            reported.current_isin = evidence.current_isin
            and reported.ex_date = evidence.ex_date
)

select
    current_isin as isin,
    ex_date,
    bse_factor,
    nse_factor,
    venues_traded,
    venues_confirming,
    basis,
    as_of_date,
    case basis
        when 'bse' then bse_factor
        when 'nse_confirmed' then nse_factor
    end as applied_factor
from judged
