-- A reviewed change of ISIN for an instrument the history holds must be one of its changes, dated
-- as stg_successions dates it, or the step check passes over a change that is not there.
select
    reviewed.successor_isin,
    reviewed.changed_on
from {{ ref('unadjusted_changes_of_isin') }} as reviewed
where
    exists (
        select 1 from {{ ref('stg_instruments') }} as instruments
        where instruments.isin = reviewed.successor_isin
    )
    and not exists (
        select 1 from {{ ref('stg_successions') }} as successions
        where
            successions.successor_isin = reviewed.successor_isin
            and successions.changed_on = reviewed.changed_on
    )
