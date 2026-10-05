{{ config(meta = {'dagster': {'ref': {'name': 'int_delivery_participation'}}}) }}

-- Delivery is a part of the day's volume. More than all of it means the two files were joined
-- across different securities, which the venue-local identifiers make possible to get wrong. A
-- venue day reviewed and listed in venue_delivery_discrepancies, on which the venue's delivery
-- file counts trades its bhavcopy does not, is passed over.
select
    participation.isin,
    participation.venue,
    participation.trade_date,
    participation.volume,
    participation.delivery_quantity
from {{ ref('int_delivery_participation') }} as participation
where
    participation.delivery_quantity > participation.volume
    and not exists (
        select 1 from {{ ref('venue_delivery_discrepancies') }} as reviewed
        where
            reviewed.venue = participation.venue
            and reviewed.trade_date = participation.trade_date
    )
