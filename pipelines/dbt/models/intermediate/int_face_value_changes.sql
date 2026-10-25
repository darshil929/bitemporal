-- Each change of ISIN of a company with the face values the venues' lists state either side of it:
-- the successor's over the predecessor's is the factor a split or consolidation applies to earlier
-- prices. It is dated by a venue's text naming the action in the days before, the day the venue
-- gave, else by the day the successor first traded.

-- Trading halts between a split's record date and its new ISIN's first day, so a venue's record of
-- the action falls within these days before the change.
{% set window_days = 10 %}

-- A fund's units carry ISINs with this prefix, and a fund's change of ISIN is read from its prices.
{% set fund_isin_prefix = 'INF' %}

with lineage as (
    select
        isin,
        current_isin
    from {{ ref('int_instrument_lineage') }}
),

changes as (
    select
        successions.predecessor_isin,
        successions.successor_isin,
        successions.changed_on,
        lineage.current_isin,
        successions.changed_on - {{ window_days }} as recorded_from
    from {{ ref('stg_successions') }} as successions
    inner join lineage on successions.successor_isin = lineage.isin
    where successions.successor_isin not like '{{ fund_isin_prefix }}%'
),

stated as (
    select
        isin,
        source_id,
        as_of_date,
        face_value
    from {{ ref('stg_instrument_face_values') }}
),

by_list as (
    select
        changes.current_isin,
        changes.predecessor_isin,
        changes.successor_isin,
        changes.changed_on,
        changes.recorded_from,
        before.source_id,
        before.face_value as predecessor_face_value,
        after.face_value as successor_face_value,
        greatest(before.as_of_date, after.as_of_date) as as_of_date
    from changes
    inner join stated as before on changes.predecessor_isin = before.isin
    inner join stated as after
        on
            changes.successor_isin = after.isin
            and before.source_id = after.source_id
),

-- A venue's text naming a split or consolidation it states no terms for.
named as (
    select
        lineage.current_isin,
        actions.ex_date
    from {{ ref('stg_corporate_actions') }} as actions
    inner join lineage on actions.isin = lineage.isin
    where
        actions.action_type = 'unhandled'
        and actions.purpose ~* 'split|splt|\mfv\M|sub-?div|consolid'
)

select
    by_list.current_isin as isin,
    by_list.predecessor_isin,
    by_list.successor_isin,
    by_list.changed_on,
    by_list.recorded_from,
    max(by_list.as_of_date) as as_of_date,
    coalesce(
        (
            select max(named.ex_date) from named
            where
                named.current_isin = by_list.current_isin
                and named.ex_date between by_list.recorded_from and by_list.changed_on
        ),
        by_list.changed_on
    ) as ex_date,
    -- BSE's list where it states both, NSE's otherwise.
    coalesce(
        max(by_list.predecessor_face_value) filter (where by_list.source_id = 'bse_scrip_list'),
        max(by_list.predecessor_face_value)
    ) as predecessor_face_value,
    coalesce(
        max(by_list.successor_face_value) filter (where by_list.source_id = 'bse_scrip_list'),
        max(by_list.successor_face_value)
    ) as successor_face_value,
    round(
        max(by_list.successor_face_value / by_list.predecessor_face_value)
        filter (where by_list.source_id = 'bse_scrip_list'),
        10
    ) as bse_ratio,
    round(
        max(by_list.successor_face_value / by_list.predecessor_face_value)
        filter (where by_list.source_id = 'nse_equity_list'),
        10
    ) as nse_ratio
from by_list
group by
    by_list.current_isin,
    by_list.predecessor_isin,
    by_list.successor_isin,
    by_list.changed_on,
    by_list.recorded_from
