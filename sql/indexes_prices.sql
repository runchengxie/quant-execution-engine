-- Centralized indexes for share_prices
CREATE INDEX IF NOT EXISTS idx_prices_date ON share_prices(Date);
CREATE UNIQUE INDEX IF NOT EXISTS idx_prices_unique ON share_prices(Ticker, Date);

