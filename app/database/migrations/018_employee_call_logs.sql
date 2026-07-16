-- 为数字员工添加详细调用日志表
CREATE TABLE IF NOT EXISTS employee_call_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id INTEGER NOT NULL,
    user_id INTEGER,
    input_text TEXT NOT NULL,
    success INTEGER NOT NULL,
    response_data TEXT,
    error_message TEXT,
    latency_ms INTEGER,
    tokens_used INTEGER,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (employee_id) REFERENCES digital_employees(id) ON DELETE CASCADE
);

-- 为查询性能添加索引
CREATE INDEX IF NOT EXISTS idx_employee_call_logs_employee_id ON employee_call_logs(employee_id);
CREATE INDEX IF NOT EXISTS idx_employee_call_logs_created_at ON employee_call_logs(created_at);
CREATE INDEX IF NOT EXISTS idx_employee_call_logs_success ON employee_call_logs(success);
