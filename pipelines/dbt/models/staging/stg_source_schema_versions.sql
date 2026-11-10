select
    source_id,
    effective_from,
    effective_to,
    version
from {{ source('market', 'source_schema_version') }}
