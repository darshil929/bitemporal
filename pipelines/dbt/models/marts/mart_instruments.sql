-- Stored as a table: a view would build every instrument's display name on each read, and would be
-- dropped for as long as the models take to rebuild, since replacing a view drops every view on it.
{{ config(
    materialized='table',
    indexes=[{'columns': ['isin'], 'unique': True}],
) }}

-- Each instrument under the name a reader knows it by, with the ISIN it trades under now: an ISIN
-- a change of face value replaced points to the one that took it over.
select
    instruments.isin,
    instruments.name,
    names.display_name,
    instruments.instrument_type,
    lineage.current_isin
from {{ ref('stg_instruments') }} as instruments
inner join {{ ref('int_instrument_display_names') }} as names on instruments.isin = names.isin
inner join {{ ref('int_instrument_lineage') }} as lineage on instruments.isin = lineage.isin
