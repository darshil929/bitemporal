select
    listing_id,
    isin,
    exchange,
    local_symbol,
    scrip_code,
    listing_date,
    delisting_date,
    closure_reason
from {{ source('market', 'listing') }}
