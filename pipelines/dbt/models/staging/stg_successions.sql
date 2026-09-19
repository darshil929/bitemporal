-- The ISIN that took an instrument over when a face value change issued a new one, as each
-- venue observed it. Both venues see the same handover, so the pair is taken once.
select distinct
    predecessor_isin,
    successor_isin,
    changed_on
from {{ source('market', 'instrument_succession') }}
