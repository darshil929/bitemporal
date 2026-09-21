-- A venue answering a request for one day with another day's file is invisible in the file itself
-- when the file carries no date. Two days of real trading never close every instrument at the same
-- price on the same volume, so a day that repeats another is a stale file stored under the wrong
-- date.
with day_contents as (
    select
        venue,
        trade_date,
        md5(
            string_agg(
                isin || ':' || close::text || ':' || volume::text, ',' order by isin
            )
        ) as contents
    from {{ ref('stg_price_daily') }}
    group by venue, trade_date
)

select
    venue,
    contents,
    count(*) as days,
    min(trade_date) as first_day,
    max(trade_date) as last_day
from day_contents
group by venue, contents
having count(*) > 1
