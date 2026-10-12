select
    source_id,
    tier,
    base_url,
    requests_per_second,
    cache_policy,
    sebi_curation_ref,
    owner_notes
from {{ source('market', 'source_registry') }}
