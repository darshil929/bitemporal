{{ config(severity = 'warn', meta = {'dagster': {'ref': {'name': 'int_face_value_changes'}}}) }}

-- A split or consolidation a venue records at a change of ISIN scales earlier prices by the ratio
-- of the face values the lists state either side of it, a bonus changing none. Another ratio, or
-- two lists differing, means a record or a list misstates the action.

-- Terms are stored to six places, so a third reads 0.333333 against a ratio of 1/3.
{% set tolerance = 0.001 %}
with lineage as (
    select
        isin,
        current_isin
    from {{ ref('int_instrument_lineage') }}
),

recorded as (
    select
        lineage.current_isin,
        actions.source_id,
        actions.ex_date,
        exp(sum(ln(actions.adjustment_factor))) as factor
    from {{ ref('stg_corporate_actions') }} as actions
    inner join lineage on actions.isin = lineage.isin
    where
        actions.action_type in ('split', 'consolidation')
        and actions.adjustment_factor is not null
    group by lineage.current_isin, actions.source_id, actions.ex_date
)

select
    changes.isin,
    changes.changed_on,
    recorded.source_id,
    recorded.ex_date,
    recorded.factor,
    changes.bse_ratio,
    changes.nse_ratio
from {{ ref('int_face_value_changes') }} as changes
left join recorded
    on
        changes.isin = recorded.current_isin
        and recorded.ex_date between changes.recorded_from and changes.changed_on
where
    changes.bse_ratio != changes.nse_ratio
    or abs(ln(recorded.factor / coalesce(changes.bse_ratio, changes.nse_ratio))) > {{ tolerance }}
