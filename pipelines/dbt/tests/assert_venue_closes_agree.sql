-- Where both venues trade heavily at a price above the grid's own steps, their closes are held
-- together, so a wide gap is a corporate action handled at one venue and not the other. A real
-- market day carries a few of those at most. A venue serving another day's file, or a parser
-- reading the wrong layout, puts hundreds of instruments apart at once, and that is what fails.
with divergent as (
    select trade_date
    from {{ ref('int_venue_spread') }}
    where
        venue_spread_bps > 500
        and comparable_turnover >= 2500000
        and least(bse_close, nse_close) >= 10
)

select
    trade_date,
    count(*) as divergent_instruments
from divergent
group by trade_date
having count(*) > 10
