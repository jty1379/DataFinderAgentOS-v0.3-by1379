-- 为数字员工添加调用统计字段
ALTER TABLE digital_employees ADD COLUMN call_count INTEGER DEFAULT 0;
ALTER TABLE digital_employees ADD COLUMN failure_count INTEGER DEFAULT 0;
