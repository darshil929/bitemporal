"""What a row of the daily features is read beside, in a statement naming the row `features`: the
instrument's symbol, and the unhandled corporate actions its figures may carry."""

# The symbol of an open listing before a closed one, the primary venue's before the other's.
SYMBOL = """
    (
        select listings.local_symbol from mart_listings as listings
        where listings.isin = features.isin
        order by listings.delisting_date is null desc,
            listings.exchange = features.primary_venue desc,
            listings.exchange = 'NSE' desc, listings.listing_date desc
        limit 1
    ) as symbol
"""

UNHANDLED_ACTIONS = "coalesce(unhandled.actions, cast('[]' as jsonb)) as unhandled_actions"

# The prices are not adjusted for an unhandled action, so one with its ex-date after the earliest of
# the `:lookback` bars before the row's day, on the row's venue, runs through a figure reading them.
UNHANDLED_ACTIONS_JOIN = """
    left join lateral (
        select coalesce(
            (
                select bars.trade_date from mart_adjusted_prices as bars
                where bars.isin = features.isin and bars.venue = features.primary_venue
                    and bars.trade_date <= features.trade_date
                order by bars.trade_date desc
                offset :lookback limit 1
            ),
            (
                select bars.trade_date from mart_adjusted_prices as bars
                where bars.isin = features.isin and bars.venue = features.primary_venue
                order by bars.trade_date
                limit 1
            )
        ) as first_day
    ) as span on true
    left join lateral (
        select jsonb_agg(
            jsonb_build_object('ex_date', actions.ex_date, 'purpose', actions.purpose)
            order by actions.ex_date desc, actions.purpose
        ) as actions
        from mart_corporate_actions as actions
        where actions.isin = features.isin and actions.action_type = 'unhandled'
            and actions.ex_date > span.first_day and actions.ex_date <= features.trade_date
    ) as unhandled on true
"""
