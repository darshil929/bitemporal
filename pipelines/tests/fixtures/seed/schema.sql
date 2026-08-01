create schema if not exists fixture;

create table fixture.instrument (
    isin text primary key,
    name text not null,
    sector text not null,
    country text not null,
    instrument_type text not null
);

create table fixture.listing (
    isin text not null references fixture.instrument (isin),
    exchange text not null,
    local_symbol text not null,
    scrip_code text,
    listing_date date not null,
    delisting_date date,
    primary key (isin, exchange, local_symbol, listing_date)
);

create table fixture.price_daily (
    isin text not null references fixture.instrument (isin),
    venue text not null,
    trade_date date not null,
    open numeric(18, 4) not null,
    high numeric(18, 4) not null,
    low numeric(18, 4) not null,
    close numeric(18, 4) not null,
    volume bigint not null,
    as_of_date date not null,
    primary key (isin, venue, trade_date)
);

create table fixture.corporate_action (
    isin text not null references fixture.instrument (isin),
    action_type text not null,
    ex_date date not null,
    ratio_from numeric(18, 6) not null,
    ratio_to numeric(18, 6) not null,
    as_of_date date not null,
    primary key (isin, action_type, ex_date)
);
