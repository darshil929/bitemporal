select
    isin,
    source_id,
    count(*) as names
from {{ ref('stg_instrument_names') }}
group by isin, source_id
having count(*) > 1
