-- Query support for provider-isolated candle history.
-- Safe to apply more than once.
create index if not exists idx_market_candles_asset_provider_history
    on public.market_candles (asset_id, provider_id, timeframe, open_time);
