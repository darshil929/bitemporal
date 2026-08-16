-- The latest reported version of each action known on the as-of date. A restated action is a
-- further row rather than a replacement.
select distinct on (isin, action_type, ex_date, qualifier, source_id)
    isin,
    action_type,
    ex_date,
    qualifier,
    source_id,
    as_of_date,
    ratio_from,
    ratio_to,
    dividend_amount,
    case
        when ratio_from is not null and ratio_to is not null
            then round(ratio_from / ratio_to, 6)
    end as adjustment_factor
from {{ source('market', 'corporate_action') }}
where as_of_date <= '{{ var("as_of_date", "9999-12-31") }}'
order by
    isin asc, action_type asc, ex_date asc, qualifier asc, source_id asc, as_of_date desc
