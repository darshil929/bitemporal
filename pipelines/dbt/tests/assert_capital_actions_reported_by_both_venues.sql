{{ config(severity = 'warn') }}

-- A count-changing action one venue reports and the other does not, for an instrument listed at
-- both that day. A day NSE reports alone scales the series only where the prices confirm it, which
-- int_capital_action_factors records.
select
    isin,
    ex_date,
    agreement,
    bse_factor,
    nse_factor
from {{ ref('int_corporate_action_agreement') }}
where agreement in ('bse_only', 'nse_only')
