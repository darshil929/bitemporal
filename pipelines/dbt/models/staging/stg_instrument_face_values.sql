-- The latest face value each list gives an instrument, known on the as-of date. A face value
-- change issues a new ISIN, so an ISIN keeps one face value, and a later one corrects it.
select distinct on (isin, source_id)
    isin,
    source_id,
    as_of_date,
    face_value
from {{ source('market', 'instrument_face_value') }}
where as_of_date <= '{{ var("as_of_date", "9999-12-31") }}'
order by isin asc, source_id asc, as_of_date desc
