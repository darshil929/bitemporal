-- The latest name each list gives an instrument, known on the as-of date. A list read on a later
-- day appends a name only where it changed, so without this every earlier name appears.
select distinct on (isin, source_id)
    isin,
    source_id,
    as_of_date,
    name
from {{ source('market', 'instrument_name') }}
where as_of_date <= '{{ var("as_of_date", "9999-12-31") }}'
order by isin asc, source_id asc, as_of_date desc
