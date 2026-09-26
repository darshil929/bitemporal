{{ config(severity = 'warn') }}

-- A count-changing action one venue reports and the other does not, for an instrument listed at
-- both that day. The series is scaled by BSE's alone, so a day NSE reports and BSE does not is one
-- the series does not cover.
select
    isin,
    ex_date,
    agreement,
    bse_factor,
    nse_factor
from {{ ref('int_corporate_action_agreement') }}
where agreement in ('bse_only', 'nse_only')
