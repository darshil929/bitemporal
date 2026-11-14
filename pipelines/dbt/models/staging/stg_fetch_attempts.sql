-- Every attempt to fetch a slice of a source, as the ingestion logged it.
select
    ingestion_id,
    source_id,
    partition_key,
    outcome,
    fetched_at,
    row_count,
    detail
from {{ source('market', 'ingestion_log') }}
where fetched_at::date <= '{{ var("as_of_date", "9999-12-31") }}'
