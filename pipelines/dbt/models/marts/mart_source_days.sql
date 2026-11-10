-- Stored as a table: the data status reads it on every page.
{{ config(
    materialized='table',
    indexes=[{'columns': ['source_id', 'trade_date'], 'unique': True}],
) }}

select
    source_id,
    trade_date,
    outcome,
    fetched_at
from {{ ref('stg_source_days') }}
