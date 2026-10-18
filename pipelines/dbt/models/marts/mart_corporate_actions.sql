-- Stored as a table: whether a split or bonus is applied is judged against every instrument's
-- prices, which a view would repeat on each read.
{{ config(
    materialized='table',
    indexes=[{'columns': ['isin', 'ex_date']}],
) }}

-- Each corporate action once, keyed on the ISIN the instrument trades under now. Both venues report
-- most actions, so BSE's record stands wherever BSE states that kind of action that day, as it
-- does for the price adjustment, and NSE's stands otherwise. A split of a fund's units no venue
-- records is listed as read from the prices.
with recorded as (
    select
        lineage.current_isin,
        actions.isin,
        actions.action_type,
        actions.ex_date,
        actions.qualifier,
        actions.source_id,
        actions.as_of_date,
        actions.ratio_from,
        actions.ratio_to,
        actions.dividend_amount,
        actions.purpose,
        actions.adjustment_factor,
        -- A text naming one dividend and no other action, in words the venue's reader left whole:
        -- BSE names a dividend before it states the amount, and NSE wrote amounts and percentages
        -- of face value in shorthand ("1st Int Div-Rs.2/- Per Sh", "Dividend - 25%").
        coalesce(
            actions.action_type = 'unhandled'
            and actions.purpose ~* '\mdiv(?!is)'
            and actions.purpose !~* (
                'bonus|\mbon\M|split|splt|\mfv\M|sub-div|consolid|right|buy ?back|demerg|spin'
                || '|scheme|amalg|arrange|reduction|warrant|debenture|capital'
            )
            and actions.purpose !~* '\+|(fin|int).*(spl|special)|(spl|special).*(fin|int)',
            false
        ) as is_dividend_text
    from {{ ref('stg_corporate_actions') }} as actions
    inner join {{ ref('int_instrument_lineage') }} as lineage on actions.isin = lineage.isin
),

-- A dividend text is a dividend whose amount is not stated, nothing where it says nil.
actions as (
    select
        current_isin,
        isin,
        ex_date,
        source_id,
        as_of_date,
        ratio_from,
        ratio_to,
        purpose,
        adjustment_factor,
        case when is_dividend_text then 'dividend' else action_type end as action_type,
        case
            when not is_dividend_text then qualifier
            when purpose ~* '\mint(erim)?\M' then 'interim'
            when purpose ~* '\mfin(al)?\M' then 'final'
            when purpose ~* '\m(spl|special)\M' then 'special'
            else 'ordinary'
        end as qualifier,
        case
            when is_dividend_text and purpose ~* '\mnil\M' then 0 else dividend_amount
        end as dividend_amount,
        is_dividend_text and purpose !~* '\mnil\M' as is_unstated
    from recorded
),

-- An unstated dividend stands only where no record that day states an amount, and then once for
-- its kind, BSE's text before NSE's and the latest before the earlier.
ordered as (
    select
        *,
        row_number() over (
            partition by current_isin, ex_date, action_type, qualifier
            order by source_id = 'bse_corporate_actions' desc, as_of_date desc, purpose asc
        ) as place
    from actions
),

reported as (
    select
        current_isin,
        ex_date,
        action_type,
        bool_or(source_id = 'bse_corporate_actions') as by_bse,
        bool_or(source_id = 'nse_corporate_actions') as by_nse,
        bool_or(source_id = 'bse_corporate_actions' and not is_unstated) as stated_by_bse,
        bool_or(not is_unstated) as is_stated,
        array_agg(dividend_amount order by dividend_amount) filter (
            where source_id = 'bse_corporate_actions' and not is_unstated
        ) as bse_amounts,
        array_agg(dividend_amount order by dividend_amount) filter (
            where source_id = 'nse_corporate_actions' and not is_unstated
        ) as nse_amounts
    from actions
    group by current_isin, ex_date, action_type
),

listed as (
    select
        actions.current_isin as isin,
        actions.isin as source_isin,
        actions.ex_date,
        actions.action_type,
        actions.qualifier,
        actions.source_id,
        actions.as_of_date,
        actions.ratio_from,
        actions.ratio_to,
        actions.adjustment_factor,
        actions.dividend_amount,
        actions.purpose,
        case
            when reported.by_bse and reported.by_nse then 'both'
            when reported.by_bse then 'BSE'
            else 'NSE'
        end as reported_by,
        coalesce(
            actions.action_type = 'dividend'
            and reported.bse_amounts is not null
            and reported.nse_amounts is not null
            and reported.bse_amounts is distinct from reported.nse_amounts,
            false
        ) as venues_differ,
        case
            when actions.action_type not in ('bonus', 'split', 'consolidation') then null
            when actions.source_id = 'bse_corporate_actions' then factors.basis = 'bse'
            else coalesce(factors.basis = 'nse_confirmed', false)
        end as is_applied
    from ordered as actions
    inner join reported
        on
            actions.current_isin = reported.current_isin
            and actions.ex_date = reported.ex_date
            and actions.action_type = reported.action_type
    left join {{ ref('int_capital_action_factors') }} as factors
        on
            actions.current_isin = factors.isin
            and actions.ex_date = factors.ex_date
    where
        (actions.source_id = 'bse_corporate_actions' or not reported.stated_by_bse)
        and (not actions.is_unstated or (not reported.is_stated and actions.place = 1))
),

read_from_prices as (
    select
        isin,
        isin as source_isin,
        ex_date,
        'split' as action_type,
        'ordinary' as qualifier,
        null as source_id,
        as_of_date,
        1 as ratio_from,
        round(1 / applied_factor) as ratio_to,
        applied_factor as adjustment_factor,
        null::numeric as dividend_amount,
        null as purpose,
        'prices' as reported_by,
        false as venues_differ,
        true as is_applied
    from {{ ref('int_capital_action_factors') }}
    where basis = 'fund_unit_split'
),

every_action as (
    select * from listed
    union all
    select * from read_from_prices
)

-- Terms as an announcement states them: a bonus as the shares given for those held, a split or
-- consolidation as the shares before and after in lowest terms, and a dividend of nothing as nil.
select
    isin,
    source_isin,
    ex_date,
    action_type,
    qualifier,
    source_id,
    as_of_date,
    ratio_from,
    ratio_to,
    adjustment_factor,
    dividend_amount,
    purpose,
    reported_by,
    venues_differ,
    is_applied,
    case
        when action_type = 'bonus'
            then trim_scale(ratio_to - ratio_from)::text || ' for ' || trim_scale(ratio_from)::text
        when action_type in ('split', 'consolidation')
            then
                trim_scale(ratio_from / gcd(ratio_from, ratio_to))::text
                || ' into '
                || trim_scale(ratio_to / gcd(ratio_from, ratio_to))::text
        when action_type = 'dividend' and dividend_amount = 0 then 'Nil'
    end as terms
from every_action
