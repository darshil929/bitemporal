-- A split or bonus both venues report must scale the price by the same factor. BSE's stands in the
-- series, so a disagreement means either the series or NSE's record of the day is wrong.
select
    isin,
    ex_date,
    bse_factor,
    nse_factor
from {{ ref('int_corporate_action_agreement') }}
where agreement = 'differ'
