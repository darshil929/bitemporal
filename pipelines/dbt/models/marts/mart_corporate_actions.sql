-- Stored as a table: whether a split or bonus is applied is judged against every instrument's
-- prices, which a view would repeat on each read.
{{ config(
    materialized='table',
    indexes=[{'columns': ['isin', 'ex_date']}],
) }}

-- Each corporate action once, keyed on the ISIN the instrument trades under now. Both venues report
-- most actions, so BSE's record stands wherever BSE states that kind of action that day, as it
-- does for the price adjustment, and NSE's stands otherwise. A split of a fund's units no venue
-- records is listed as read from the prices, a day whose terms were reviewed lists the reviewed
-- terms in place of the venues', and a change of ISIN no venue records terms for lists the split
-- or consolidation the venues' lists state face values for.
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
        ) as is_dividend_text,
        -- The count-changing action a record states, or that a text names without terms read.
        case
            when actions.action_type in ('bonus', 'split', 'consolidation') then actions.action_type
            when actions.action_type != 'unhandled' then null
            when actions.purpose ~* 'bonus|\mbon\M' then 'bonus'
            when actions.purpose ~* 'split|splt|\mfv\M|sub-?div' then 'split'
            when actions.purpose ~* 'consolid' then 'consolidation'
        end as capital_kind
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
        capital_kind,
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

reviewed as (
    select
        lineage.current_isin,
        reviewed.isin,
        reviewed.ex_date,
        reviewed.action_type,
        reviewed.reviewed_on,
        reviewed.ratio_from,
        reviewed.ratio_to,
        reviewed.reason,
        coalesce(
            reviewed.adjustment_factor, round(reviewed.ratio_from / reviewed.ratio_to, 6)
        ) as adjustment_factor
    from {{ ref('reviewed_capital_actions') }} as reviewed
    inner join {{ ref('int_instrument_lineage') }} as lineage on reviewed.isin = lineage.isin
    where reviewed.reviewed_on <= '{{ var("as_of_date", "9999-12-31") }}'
),

-- The venues that record each count-changing action, or a text naming it, on a day.
venue_records as (
    select
        current_isin,
        ex_date,
        capital_kind,
        bool_or(source_id = 'bse_corporate_actions') as by_bse,
        bool_or(source_id = 'nse_corporate_actions') as by_nse
    from actions
    where capital_kind is not null
    group by current_isin, ex_date, capital_kind
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
        end as is_applied,
        false as is_reviewed,
        null as review_reason
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
        and not (
            actions.capital_kind is not null
            and (
                factors.basis is not distinct from 'face_value_change'
                or exists (
                    select 1 from reviewed
                    where
                        reviewed.current_isin = actions.current_isin
                        and reviewed.ex_date = actions.ex_date
                )
            )
        )
),

-- Each reviewed action, reported by the venues whose records of that action it stands for.
reviewed_listed as (
    select
        reviewed.current_isin as isin,
        reviewed.isin as source_isin,
        reviewed.ex_date,
        reviewed.action_type,
        'ordinary' as qualifier,
        null as source_id,
        reviewed.reviewed_on as as_of_date,
        reviewed.ratio_from,
        reviewed.ratio_to,
        reviewed.adjustment_factor,
        null::numeric as dividend_amount,
        null as purpose,
        case
            when venue_records.by_bse and venue_records.by_nse then 'both'
            when venue_records.by_bse then 'BSE'
            else 'NSE'
        end as reported_by,
        false as venues_differ,
        true as is_applied,
        true as is_reviewed,
        reviewed.reason as review_reason
    from reviewed
    inner join venue_records
        on
            reviewed.current_isin = venue_records.current_isin
            and reviewed.ex_date = venue_records.ex_date
            and reviewed.action_type = venue_records.capital_kind
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
        true as is_applied,
        false as is_reviewed,
        null as review_reason
    from {{ ref('int_capital_action_factors') }}
    where basis = 'fund_unit_split'
),

-- Shares before and after stand in the ratio of the face values after and before.
read_from_face_values as (
    select
        factors.isin,
        changes.predecessor_isin as source_isin,
        factors.ex_date,
        case
            when changes.successor_face_value < changes.predecessor_face_value then 'split'
            else 'consolidation'
        end as action_type,
        'ordinary' as qualifier,
        case
            when changes.bse_ratio is not null then 'bse_scrip_list' else 'nse_equity_list'
        end as source_id,
        factors.as_of_date,
        changes.successor_face_value as ratio_from,
        changes.predecessor_face_value as ratio_to,
        factors.applied_factor as adjustment_factor,
        null::numeric as dividend_amount,
        null as purpose,
        case
            when changes.bse_ratio is not null and changes.nse_ratio is not null then 'both'
            when changes.bse_ratio is not null then 'BSE'
            else 'NSE'
        end as reported_by,
        false as venues_differ,
        true as is_applied,
        false as is_reviewed,
        null as review_reason
    from {{ ref('int_capital_action_factors') }} as factors
    inner join {{ ref('int_face_value_changes') }} as changes
        on
            factors.isin = changes.isin
            and factors.ex_date = changes.ex_date
    where factors.basis = 'face_value_change'
),

every_action as (
    select * from listed
    union all
    select * from reviewed_listed
    union all
    select * from read_from_prices
    union all
    select * from read_from_face_values
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
    is_reviewed,
    review_reason,
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
