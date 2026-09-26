-- The factor the continuous series applies on each day either venue reports a count-changing
-- action. Each venue misses actions the other records, and NSE has filed an action under the
-- wrong company, so neither is taken alone: BSE's actions stand, and a day NSE alone reports is
-- applied only where the close moved by its factor at every venue that traded either side of the
-- ex-date.
--
-- Neither venue records a split of a fund's units, which issues the units a new ISIN. A fund's
-- price follows the value of what it holds, so across that change of ISIN its close falls by the
-- split's ratio, and a fund's change of ISIN no venue reports an action for is applied where every
-- venue that traded across it moved by the same ratio.

-- A venue's closes within this many days either side of the ex-date measure its move there. A
-- venue that did not trade on both sides within it is not counted.
{% set window_days = 10 %}

-- A thinly traded company can go weeks without a trade. Where no venue traded within the window,
-- each venue's nearest closes within this many days either side measure the move instead.
{% set quiet_window_days = 92 %}

-- A move confirms a factor when it lies within this distance of it in log terms, and nearer to it
-- than to no action at all. A company held at a 20 percent circuit limit on its ex-date moves 0.18
-- from its factor.
{% set tolerance = 0.25 %}

-- A face value steps through 1, 2 and 5 and their multiples of ten, so a split divides it by one
-- of these ratios. A ratio of 1 is a change of ISIN that split nothing. Neighbouring ratios lie at
-- least twice the tolerance apart, so a move reads as one ratio at most.
{% set face_value_ratios = [1, 2, 5, 10, 20, 50, 100, 200, 500, 1000] %}

-- An ISIN issued to a mutual fund's units begins with this prefix.
{% set fund_isin_prefix = 'INF' %}

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
-- a split that issued a new ISIN is measured from the retired one to its successor. The lineage's
-- ISINs are passed to each lookup as one array, which reads only that instrument's bars.
moves as (
    select
        reported.current_isin,
        reported.ex_date,
        venues.venue,
        ln(after.close / before.close) as log_move,
        greatest(reported.ex_date - before.trade_date, after.trade_date - reported.ex_date)
        <= {{ window_days }} as is_near,
        greatest(before.as_of_date, after.as_of_date) as as_of_date
    from reported
    cross join
        lateral (
            select array_agg(lineage.isin) as isins
            from lineage
            where lineage.current_isin = reported.current_isin
        ) as family
    cross join (values ('BSE'), ('NSE')) as venues (venue)
    inner join lateral (
        select
            prices.close,
            prices.trade_date,
            prices.as_of_date
        from {{ ref('stg_price_daily') }} as prices
        where
            prices.isin = any(family.isins)
            and prices.venue = venues.venue
            and prices.trade_date < reported.ex_date
            and prices.trade_date >= reported.ex_date - {{ quiet_window_days }}
        order by prices.trade_date desc
        limit 1
    ) as before on true
    inner join lateral (
        select
            prices.close,
            prices.trade_date,
            prices.as_of_date
        from {{ ref('stg_price_daily') }} as prices
        where
            prices.isin = any(family.isins)
            and prices.venue = venues.venue
            and prices.trade_date >= reported.ex_date
            and prices.trade_date < reported.ex_date + {{ quiet_window_days }}
        order by prices.trade_date asc
        limit 1
    ) as after on true
    where reported.bse_factor is null
),

-- A venue that traded within the window counts, and where none did, every venue that traded
-- within the quiet window counts.
counted as (
    select *
    from (
        select
            moves.*,
            bool_or(moves.is_near) over (
                partition by moves.current_isin, moves.ex_date
            ) as any_near
        from moves
    ) as flagged
    where is_near or not any_near
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
    from counted as moves
    inner join reported
        on
            moves.current_isin = reported.current_isin
            and moves.ex_date = reported.ex_date
    group by moves.current_isin, moves.ex_date
),

-- Each change of ISIN of a fund's units, measured at each venue from the last close of the
-- retired ISIN to the first close of its successor, and read as the nearest face value ratio.
fund_moves as (
    select
        lineage.current_isin,
        successions.changed_on as ex_date,
        venues.venue,
        ln(before.close / after.close) as log_ratio,
        greatest(before.as_of_date, after.as_of_date) as as_of_date
    from {{ ref('stg_successions') }} as successions
    inner join lineage on successions.successor_isin = lineage.isin
    cross join (values ('BSE'), ('NSE')) as venues (venue)
    inner join lateral (
        select
            prices.close,
            prices.as_of_date
        from {{ ref('stg_price_daily') }} as prices
        where
            prices.isin = successions.predecessor_isin
            and prices.venue = venues.venue
            and prices.trade_date < successions.changed_on
            and prices.trade_date >= successions.changed_on - {{ window_days }}
        order by prices.trade_date desc
        limit 1
    ) as before on true
    inner join lateral (
        select
            prices.close,
            prices.as_of_date
        from {{ ref('stg_price_daily') }} as prices
        where
            prices.isin = successions.successor_isin
            and prices.venue = venues.venue
            and prices.trade_date >= successions.changed_on
            and prices.trade_date < successions.changed_on + {{ window_days }}
        order by prices.trade_date asc
        limit 1
    ) as after on true
    where successions.successor_isin like '{{ fund_isin_prefix }}%'
),

fund_ratios as (
    select
        fund_moves.current_isin,
        fund_moves.ex_date,
        fund_moves.as_of_date,
        nearest.ratio
    from fund_moves
    left join lateral (
        select candidates.ratio
        from (
            values
            {% for ratio in face_value_ratios -%}
                ({{ ratio }}){{ "," if not loop.last }}
            {% endfor %}
        ) as candidates (ratio)
        where abs(fund_moves.log_ratio - ln(candidates.ratio)) <= {{ tolerance }}
    ) as nearest on true
),

-- A split every venue that traded across the change reads alike, on a day no venue reports an
-- action within the window.
fund_splits as (
    select
        current_isin,
        ex_date,
        count(*) as venues_traded,
        count(ratio) as venues_confirming,
        min(ratio) as ratio,
        max(as_of_date) as as_of_date
    from fund_ratios
    group by current_isin, ex_date
    having
        count(ratio) = count(*)
        and min(ratio) = max(ratio)
        and min(ratio) > 1
),

unreported_fund_splits as (
    select fund_splits.*
    from fund_splits
    where not exists (
        select 1 from reported
        where
            reported.current_isin = fund_splits.current_isin
            and abs(reported.ex_date - fund_splits.ex_date) < {{ window_days }}
    )
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
        end as as_of_date,
        null::numeric as fund_factor
    from reported
    left join evidence
        on
            reported.current_isin = evidence.current_isin
            and reported.ex_date = evidence.ex_date

    union all

    select
        current_isin,
        ex_date,
        null as bse_factor,
        null as nse_factor,
        venues_traded,
        venues_confirming,
        'fund_unit_split' as basis,
        as_of_date,
        round(1.0 / ratio, 10) as fund_factor
    from unreported_fund_splits
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
        when 'fund_unit_split' then fund_factor
    end as applied_factor
from judged
