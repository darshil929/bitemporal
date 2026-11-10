-- The latest answer each daily source gave for each day known on the as-of date. A day is asked
-- again until its file is published, so without this every earlier attempt appears.
select distinct on (source_id, partition_key)
    source_id,
    partition_key::date as trade_date,
    outcome,
    fetched_at
from {{ source('market', 'ingestion_log') }}
where
    partition_key ~ '^\d{4}-\d{2}-\d{2}$'
    and fetched_at::date <= '{{ var("as_of_date", "9999-12-31") }}'
order by source_id asc, partition_key asc, fetched_at desc
