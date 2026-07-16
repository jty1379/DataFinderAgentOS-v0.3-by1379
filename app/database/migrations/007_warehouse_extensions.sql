-- Add new columns to warehouse_items for enhanced features
-- Keywords support, risk level, and security analysis

ALTER TABLE warehouse_items ADD COLUMN keywords TEXT NOT NULL DEFAULT '' CHECK (length(keywords) <= 500);
ALTER TABLE warehouse_items ADD COLUMN risk_level TEXT NOT NULL DEFAULT 'normal' CHECK (risk_level IN ('low', 'normal', 'high', 'critical'));
ALTER TABLE warehouse_items ADD COLUMN matched_words TEXT NOT NULL DEFAULT '' CHECK (length(matched_words) <= 500);
ALTER TABLE warehouse_items ADD COLUMN security_analysis TEXT NOT NULL DEFAULT '{}';

-- Create index for risk_level queries
CREATE INDEX IF NOT EXISTS idx_warehouse_risk_level ON warehouse_items(risk_level);
CREATE INDEX IF NOT EXISTS idx_warehouse_keywords ON warehouse_items(keywords);
