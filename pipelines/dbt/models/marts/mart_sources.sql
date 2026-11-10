with first_days as (
    select
        source_id,
        min(effective_from) as first_day
    from {{ ref('stg_source_schema_versions') }}
    group by source_id
)

select
    registry.source_id,
    registry.tier,
    registry.sebi_curation_ref,
    registry.base_url,
    first_days.first_day
from {{ ref('stg_source_registry') }} as registry
left join first_days on registry.source_id = first_days.source_id
