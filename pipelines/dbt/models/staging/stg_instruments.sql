select
    isin,
    name,
    sector,
    country,
    instrument_type
from {{ source('market', 'instrument_master') }}
