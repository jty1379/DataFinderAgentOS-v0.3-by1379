-- 数据分析师改用卡片渲染，前端呈现 KPI/柱状图/表格，而非原始 JSON 转储。
UPDATE digital_employees
SET response_mode='card', updated_at=CURRENT_TIMESTAMP
WHERE code='analyst';
