-- An unhandled action is only as good as the text that records it, and a price move it caused
-- cannot be explained without one.
select
    isin,
    ex_date,
    source_id
from {{ ref('stg_corporate_actions') }}
where action_type = 'unhandled' and purpose is null
