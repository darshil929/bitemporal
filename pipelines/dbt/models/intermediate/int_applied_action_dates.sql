-- Stored as a table: whether a factor applies is judged against the prices of every instrument,
-- which a read naming a few instruments would otherwise repeat for each of them. Its rows are
-- replaced in one transaction rather than the table itself: a new table drops the views built on
-- it, and a view also over the series table waits for that table's build of several minutes
-- before dbt rebuilds it.
{{ config(
    materialized='incremental',
    incremental_strategy='append',
    pre_hook="{% if is_incremental() %}delete from {{ this }}{% endif %}",
    indexes=[{'columns': ['isin', 'ex_date'], 'unique': True}],
) }}

-- The day each factor the continuous series applies became knowable. A factor NSE alone reports
-- is known once the prices after its ex-date confirm it, which can be days after the report.
select
    isin,
    ex_date,
    max(as_of_date) as as_of_date
from {{ ref('int_capital_action_factors') }}
where applied_factor is not null
group by isin, ex_date
