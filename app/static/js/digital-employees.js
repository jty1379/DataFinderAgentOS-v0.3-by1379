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
})();
