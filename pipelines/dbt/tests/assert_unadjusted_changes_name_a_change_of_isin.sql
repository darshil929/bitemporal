{{ config(meta = {'dagster': {'ref': {'name': 'unadjusted_changes_of_isin'}}}) }}

-- A reviewed change of ISIN for an instrument the history holds must be one of its changes, dated
-- as stg_successions dates it, or the step check passes over a change that is not there. A
-- succession is drawn from the predecessor's last days, so a change is asked for only where the
-- history holds the week before it: a history loaded from a later day holds neither side.
select
    reviewed.successor_isin,
    reviewed.changed_on
from {{ ref('unadjusted_changes_of_isin') }} as reviewed
where
    exists (
        select 1 from {{ ref('stg_instruments') }} as instruments
        where instruments.isin = reviewed.successor_isin
    )
    and exists (
        select 1 from {{ ref('stg_price_daily') }} as prices
        where
            prices.trade_date >= reviewed.changed_on - 7
            and prices.trade_date < reviewed.changed_on
    )
    and not exists (
        select 1 from {{ ref('stg_successions') }} as successions
        where
            successions.successor_isin = reviewed.successor_isin
            and successions.changed_on = reviewed.changed_on
    )
