{{ config(meta = {'dagster': {'ref': {'name': 'reviewed_capital_actions'}}}) }}

-- A reviewed action of an instrument the history holds stands for a venue's record of that kind of
-- action on that day, or a text naming it, and is listed in its place. One standing for no record
-- would apply terms to a day on which neither venue records that action.
select
    reviewed.isin,
    reviewed.ex_date,
    reviewed.action_type
from {{ ref('reviewed_capital_actions') }} as reviewed
inner join {{ ref('int_instrument_lineage') }} as lineage on reviewed.isin = lineage.isin
where
    reviewed.reviewed_on <= '{{ var("as_of_date", "9999-12-31") }}'
    and not exists (
        select 1 from {{ ref('mart_corporate_actions') }} as listed
        where
            listed.isin = lineage.current_isin
            and listed.ex_date = reviewed.ex_date
            and listed.action_type = reviewed.action_type
            and listed.is_reviewed
    )
