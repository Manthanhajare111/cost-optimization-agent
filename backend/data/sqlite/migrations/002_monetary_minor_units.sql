ALTER TABLE resources ADD COLUMN current_rate_minor INTEGER;
UPDATE resources
SET current_rate_minor = CAST(ROUND(current_rate * 100) AS INTEGER)
WHERE current_rate IS NOT NULL AND current_rate_minor IS NULL;

ALTER TABLE rate_cards ADD COLUMN bill_rate_minor INTEGER;
UPDATE rate_cards
SET bill_rate_minor = CAST(ROUND(bill_rate * 100) AS INTEGER)
WHERE bill_rate IS NOT NULL AND bill_rate_minor IS NULL;

ALTER TABLE optimization_scenarios ADD COLUMN baseline_cost_minor INTEGER;
ALTER TABLE optimization_scenarios ADD COLUMN future_cost_minor INTEGER;
ALTER TABLE optimization_scenarios ADD COLUMN monthly_savings_minor INTEGER;
ALTER TABLE optimization_scenarios ADD COLUMN annual_savings_minor INTEGER;
UPDATE optimization_scenarios
SET baseline_cost_minor = CAST(ROUND(baseline_cost * 100) AS INTEGER),
    future_cost_minor = CAST(ROUND(future_cost * 100) AS INTEGER),
    monthly_savings_minor = CAST(ROUND(monthly_savings * 100) AS INTEGER),
    annual_savings_minor = CAST(ROUND(annual_savings * 100) AS INTEGER)
WHERE baseline_cost_minor IS NULL;

ALTER TABLE purchase_orders ADD COLUMN amount_minor INTEGER;
UPDATE purchase_orders
SET amount_minor = CAST(ROUND(amount * 100) AS INTEGER)
WHERE amount IS NOT NULL AND amount_minor IS NULL;

ALTER TABLE invoices ADD COLUMN invoiced_amount_minor INTEGER;
UPDATE invoices
SET invoiced_amount_minor = CAST(ROUND(invoiced_amount * 100) AS INTEGER)
WHERE invoiced_amount IS NOT NULL AND invoiced_amount_minor IS NULL;

ALTER TABLE procurement_contracts ADD COLUMN negotiated_rate_minor INTEGER;
UPDATE procurement_contracts
SET negotiated_rate_minor = CAST(ROUND(negotiated_rate * 100) AS INTEGER)
WHERE negotiated_rate IS NOT NULL AND negotiated_rate_minor IS NULL;

ALTER TABLE procurement_recommendations ADD COLUMN estimated_savings_minor INTEGER;
UPDATE procurement_recommendations
SET estimated_savings_minor = CAST(ROUND(estimated_savings * 100) AS INTEGER)
WHERE estimated_savings IS NOT NULL AND estimated_savings_minor IS NULL;

CREATE INDEX IF NOT EXISTS idx_rate_cards_minor_units ON rate_cards(currency, bill_rate_minor);
