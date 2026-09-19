-- Every ISIN mapped to the one it has become, following each change of face value forward
-- until no further ISIN took over. An instrument that never split maps to itself, so joining
-- through this model never drops a row.
with recursive pairs as (
    select
        predecessor_isin,
        successor_isin
    from {{ ref('stg_successions') }}
),

walk as (
    select
        isin,
        isin as current_isin
    from {{ ref('stg_instruments') }}

    union all

    select
        walk.isin,
        pairs.successor_isin
    from walk
    inner join pairs on walk.current_isin = pairs.predecessor_isin
)

select
    walk.isin,
    walk.current_isin
from walk
where not exists (
    select 1
    from pairs
    where pairs.predecessor_isin = walk.current_isin
)
