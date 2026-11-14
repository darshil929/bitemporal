-- A view, so a run's attempts read as they are logged while it goes.
select
    ingestion_id,
    source_id,
    partition_key,
    outcome,
    fetched_at,
    row_count,
    detail
from {{ ref('stg_fetch_attempts') }}
