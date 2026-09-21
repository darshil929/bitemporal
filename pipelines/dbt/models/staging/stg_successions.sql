-- The ISIN that took an instrument over when a face value change issued a new one. Both venues
-- observe the same handover, often a trading day apart, so the pair is taken once and dated by
-- the first day the successor traded at either.
select
    predecessor_isin,
    successor_isin,
    min(changed_on) as changed_on
from {{ source('market', 'instrument_succession') }}
group by predecessor_isin, successor_isin
