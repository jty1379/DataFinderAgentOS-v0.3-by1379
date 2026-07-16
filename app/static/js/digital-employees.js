(function () {
    "use strict";
    const api = window.DataFinderAdmin;
    const cards = window.DataFinderCards;
    if (!api || !cards) return;

    function syncForm(form) {
        const type = form.querySelector("[data-agent-type]")?.value || "llm";
        form.querySelectorAll("[data-agent-llm]").forEach((node) => node.hidden = type !== "llm");
        form.querySelectorAll("[data-agent-api]").forEach((node) => node.hidden = type !== "api");
    }
    api.qsa("[data-agent-form]").forEach((form) => {
        syncForm(form);
        form.querySelector("[data-agent-type]")?.addEventListener("change", () => syncForm(form));
    });

    const dialog = api.qs("#agent-preview");
    const previewForm = api.qs("[data-agent-preview-form]");
    const resultBox = api.qs("[data-preview-result]");
    api.qsa("[data-agent-preview]").forEach((button) => {
        button.addEventListener("click", () => {
            api.qs("[data-preview-agent-id]").value = button.dataset.agentPreview;
            api.qs("[data-agent-preview-title]").textContent = `后台预览 · ${button.dataset.agentName}`;
            resultBox.innerHTML = "<p>输入任务后点击“执行预览”。</p>";
            dialog.showModal();
        });
    });

    function renderData(value) {
        if (value === null || typeof value !== "object") return `<span>${api.escapeHtml(String(value ?? ""))}</span>`;
        if (Array.isArray(value)) return `<div class="preview-json-list">${value.slice(0, 20).map(renderData).join("")}</div>`;
        return `<dl class="preview-data-card">${Object.entries(value).slice(0, 30).map(([key, item]) => `<div><dt>${api.escapeHtml(key)}</dt><dd>${typeof item === "object" ? renderData(item) : api.escapeHtml(String(item ?? ""))}</dd></div>`).join("")}</dl>`;
    }

    previewForm?.addEventListener("submit", async (event) => {
        event.preventDefault();
        const button = api.qs("[data-preview-submit]", previewForm);
        const input = api.qs("[data-preview-input]", previewForm).value.trim();
        if (!input) return api.announce("请输入测试任务", "error");
        api.setBusy(button, true, "执行中…");
        resultBox.innerHTML = "<p>正在调度数字员工，请稍候…</p>";
        try {
            const data = await api.fetchJson("/admin/agents/preview", {
                method: "POST", headers: {"Content-Type": "application/json"},
                body: JSON.stringify({employee_id: api.qs("[data-preview-agent-id]").value, input}),
                timeoutMs: 95000
            });
            const output = data.result;
            resultBox.replaceChildren();
            const header = document.createElement("header");
            const mention = document.createElement("b");
            mention.textContent = output.mention;
            const service = document.createElement("span");
            service.textContent = output.mode === "text" ? (output.model || "模型") : (output.mode === "card" ? "数据卡片" : "JSON");
            header.append(mention, service);
            resultBox.append(header);
            if (output.mode === "text") {
                const text = document.createElement("pre");
                text.textContent = output.text;
                resultBox.append(text);
            } else if (output.mode === "card") {
                resultBox.append(cards.render(output.data));
            } else {
                const data = document.createElement("div");
                data.innerHTML = renderData(output.data);
                resultBox.append(data);
            }
        } catch (error) {
            resultBox.innerHTML = `<p class="preview-error">${api.escapeHtml(api.errorMessage(error))}</p>`;
        } finally {
            api.setBusy(button, false);
        }
    });

    // 健康状态查看
    const healthDialog = api.qs("#agent-health-dialog");
    const healthResultBox = api.qs("[data-health-result]");
    let currentHealthEmployeeId = null;

    api.qsa("[data-agent-health]").forEach((button) => {
        button.addEventListener("click", () => {
            currentHealthEmployeeId = button.dataset.agentHealth;
            api.qs("[data-health-title]").textContent = `健康状态 · ${button.dataset.agentName}`;
            healthResultBox.innerHTML = "<p>正在加载健康状态…</p>";
            healthDialog.showModal();
            loadHealth(currentHealthEmployeeId);
        });
    });

    api.qs("[data-health-refresh]")?.addEventListener("click", () => {
        if (currentHealthEmployeeId) loadHealth(currentHealthEmployeeId);
    });

    async function loadHealth(employeeId) {
        try {
            const data = await api.fetchJson(`/admin/agents/health?id=${employeeId}`);
            const health = data.health;
            const statusClass = health.healthy ? "success" : "error";
            const statusText = health.healthy ? "健康" : "异常";

            healthResultBox.innerHTML = `
                <div class="health-summary">
                    <div class="health-status ${statusClass}">
                        <i class="layui-icon ${health.healthy ? 'layui-icon-ok-circle' : 'layui-icon-close-fill'}"></i>
                        <span>${statusText}</span>
                    </div>
                    <p>${api.escapeHtml(health.message)}</p>
                    <dl class="health-stats">
                        <div><dt>总调用次数</dt><dd>${health.call_count || 0}</dd></div>
                        <div><dt>失败次数</dt><dd>${health.failure_count || 0}</dd></div>
                        ${health.recent_failure_rate ? `<div><dt>近期失败率</dt><dd>${api.escapeHtml(health.recent_failure_rate)}</dd></div>` : ""}
                        ${health.avg_latency_ms ? `<div><dt>平均响应时间</dt><dd>${health.avg_latency_ms} ms</dd></div>` : ""}
                        ${health.last_call_at ? `<div><dt>最后调用时间</dt><dd>${api.escapeHtml(health.last_call_at)}</dd></div>` : ""}
                    </dl>
                </div>
            `;
        } catch (error) {
            healthResultBox.innerHTML = `<p class="preview-error">${api.escapeHtml(error.message)}</p>`;
        }
    }

    // 调用日志查看
    const logsDialog = api.qs("#agent-logs-dialog");
    const logsResultBox = api.qs("[data-logs-result]");
    let currentLogsEmployeeId = null;

    api.qsa("[data-agent-logs]").forEach((button) => {
        button.addEventListener("click", () => {
            currentLogsEmployeeId = button.dataset.agentLogs;
            api.qs("[data-logs-title]").textContent = `调用日志 · ${button.dataset.agentName}`;
            logsResultBox.innerHTML = "<p>正在加载调用日志…</p>";
            logsDialog.showModal();
            loadLogs(currentLogsEmployeeId);
        });
    });

    api.qs("[data-logs-refresh]")?.addEventListener("click", () => {
        if (currentLogsEmployeeId) loadLogs(currentLogsEmployeeId);
    });

    async function loadLogs(employeeId) {
        try {
            const data = await api.fetchJson(`/admin/agents/logs?id=${employeeId}&limit=20`);
            const logs = data.logs;

            if (!logs || logs.length === 0) {
                logsResultBox.innerHTML = "<p>暂无调用记录</p>";
                return;
            }

            const logRows = logs.map(log => `
                <tr class="${log.success ? "" : "error-row"}">
                    <td>${api.escapeHtml(log.created_at || "")}</td>
                    <td>${log.success ? '<span class="status-success">成功</span>' : '<span class="status-error">失败</span>'}</td>
                    <td class="log-input">${api.escapeHtml((log.input_text || "").substring(0, 50))}${(log.input_text || "").length > 50 ? "…" : ""}</td>
                    <td>${log.latency_ms ? log.latency_ms + " ms" : "-"}</td>
                    <td>${log.tokens_used || "-"}</td>
                    <td class="log-error">${log.error_message ? api.escapeHtml(log.error_message.substring(0, 100)) : "-"}</td>
                </tr>
            `).join("");

            logsResultBox.innerHTML = `
                <table class="v02-table agent-logs-table">
                    <thead>
                        <tr>
                            <th>调用时间</th>
                            <th>状态</th>
                            <th>输入内容</th>
                            <th>响应时间</th>
                            <th>Token数</th>
                            <th>错误信息</th>
                        </tr>
                    </thead>
                    <tbody>${logRows}</tbody>
                </table>
            `;
        } catch (error) {
            logsResultBox.innerHTML = `<p class="preview-error">${api.escapeHtml(error.message)}</p>`;
        }
    }
})();
