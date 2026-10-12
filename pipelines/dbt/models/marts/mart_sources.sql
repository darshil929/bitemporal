select
    source_id,
    tier,
    sebi_curation_ref,
    base_url
from {{ ref('stg_source_registry') }}
