(function () {
    "use strict";
    const api = window.DataFinderAdmin;
    if (!api) return;

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
            if (output.mode === "text") {
                resultBox.innerHTML = `<header><b>${api.escapeHtml(output.mention)}</b><span>${api.escapeHtml(output.model || "模型")}</span></header><pre>${api.escapeHtml(output.text)}</pre>`;
            } else {
                resultBox.innerHTML = `<header><b>${api.escapeHtml(output.mention)}</b><span>${output.mode === "card" ? "数据卡片" : "JSON"}</span></header>${renderData(output.data)}`;
            }
        } catch (error) {
            resultBox.innerHTML = `<p class="preview-error">${api.escapeHtml(error.message)}</p>`;
        } finally {
            api.setBusy(button, false);
        }
    });
})();
