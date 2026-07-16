(function () {
    "use strict";

    const api = window.DataFinderAdmin;
    if (!api) return;

    const form = api.qs("[data-lookout-form]");
    const keywordInput = api.qs("#lookout-keyword");
    const ruleSelect = api.qs("[data-rule-select]");
    const pageInput = api.qs("[data-page-input]");
    const pageSizeInput = api.qs("[data-page-size-input]");
    const ruleContext = api.qs("[data-rule-context]");
    const region = api.qs("[data-result-region]");
    const resultCount = api.qs("[data-result-count]");
    const selectAll = api.qs("[data-select-all]");
    const selectionCount = api.qs("[data-selection-count]");
    const importButton = api.qs("[data-import-results]");
    if (!form || !region) return;

    const state = {items: [], selected: new Set(), lastRequest: null};

    function safeUrl(value) {
        try {
            const url = new URL(value, window.location.origin);
            return ["http:", "https:"].includes(url.protocol) ? url.href : "#";
        } catch (_) {
            return "#";
        }
    }

    function updatePipeline(activeName, completed = []) {
        api.qsa("[data-pipeline-step]").forEach((step) => {
            const name = step.dataset.pipelineStep;
            step.classList.toggle("active", name === activeName);
            step.classList.toggle("done", completed.includes(name));
        });
    }

    function updateRuleContext() {
        if (!ruleSelect || !ruleSelect.selectedOptions.length) return;
        const option = ruleSelect.selectedOptions[0];
        const size = Math.min(Number(option.dataset.pageSize) || 12, 12);
        if (pageSizeInput && !pageSizeInput.dataset.edited) pageSizeInput.value = String(size);
        ruleContext.textContent = `当前规则：${option.dataset.source}；关键词参数 ${option.dataset.keywordParam}，页码参数 ${option.dataset.pageParam}，分页步长 ${option.dataset.pageStep}。`;
    }

    function updateSelection() {
        const total = state.items.length;
        const selected = state.selected.size;
        selectionCount.textContent = `已选择 ${selected} 条`;
        selectAll.disabled = total === 0;
        selectAll.checked = total > 0 && selected === total;
        selectAll.indeterminate = selected > 0 && selected < total;
        importButton.disabled = selected === 0;
        api.qsa("[data-result-select]", region).forEach((checkbox) => {
            checkbox.checked = state.selected.has(checkbox.value);
        });
    }

    function showLoading() {
        region.setAttribute("aria-busy", "true");
        region.innerHTML = '<div class="v02-feedback"><div class="skeleton-grid" aria-hidden="true"><span class="skeleton-card"></span><span class="skeleton-card"></span><span class="skeleton-card"></span></div><p>正在请求公开数据，请稍候…</p></div>';
        resultCount.textContent = "采集中";
    }

    function showError(message) {
        region.setAttribute("aria-busy", "false");
        region.innerHTML = `<div class="v02-feedback" role="alert"><i class="layui-icon layui-icon-close-fill"></i><h4>采集未完成</h4><p>${api.escapeHtml(message)}</p><button class="v02-button-secondary" type="button" data-retry-collect>重新尝试</button></div>`;
        resultCount.textContent = "采集失败";
        api.qs("[data-retry-collect]", region)?.addEventListener("click", () => form.requestSubmit());
    }

    function showEmpty(message) {
        region.setAttribute("aria-busy", "false");
        region.innerHTML = `<div class="v02-feedback"><i class="layui-icon layui-icon-search"></i><h4>没有采集到结果</h4><p>${api.escapeHtml(message || "可更换关键词、规则或页码后重试。")}</p></div>`;
        resultCount.textContent = "0 条结果";
    }

    function renderResults(items) {
        state.items = items.slice(0, 12);
        state.selected.clear();
        region.setAttribute("aria-busy", "false");
        if (!state.items.length) {
            showEmpty();
            updateSelection();
            return;
        }
        const cards = state.items.map((item) => {
            const id = String(item.id);
            const href = safeUrl(item.url);
            return `<article class="result-card">
                <label class="result-select-control"><input class="result-select" type="checkbox" value="${api.escapeHtml(id)}" data-result-select><span class="visually-hidden">选择结果：${api.escapeHtml(item.title)}</span></label>
                <span class="result-card-source">${api.escapeHtml(item.source_name || "未知来源")}</span>
                <h4>${api.escapeHtml(item.title || "未命名结果")}</h4>
                <p>${api.escapeHtml(item.summary || "该结果暂未提供摘要，请打开原文核对。")}</p>
                <footer><span>${api.escapeHtml(item.published_at || "时间未知")}</span><a href="${api.escapeHtml(href)}" target="_blank" rel="noopener noreferrer">查看原文<i class="layui-icon layui-icon-right"></i></a></footer>
            </article>`;
        }).join("");
        region.innerHTML = `<div class="result-grid">${cards}</div>`;
        resultCount.textContent = `${state.items.length} 条结果`;
        api.qsa("[data-result-select]", region).forEach((checkbox) => {
            checkbox.addEventListener("change", () => {
                if (checkbox.checked) state.selected.add(checkbox.value);
                else state.selected.delete(checkbox.value);
                updateSelection();
            });
        });
        updateSelection();
        updatePipeline("result", ["query", "rule"]);
    }

    ruleSelect?.addEventListener("change", updateRuleContext);
    pageSizeInput?.addEventListener("input", () => { pageSizeInput.dataset.edited = "true"; });
    updateRuleContext();

    selectAll?.addEventListener("change", () => {
        state.selected.clear();
        if (selectAll.checked) state.items.forEach((item) => state.selected.add(String(item.id)));
        updateSelection();
    });

    form.addEventListener("submit", async (event) => {
        event.preventDefault();
        const button = api.qs("button[type='submit']", form);
        const keyword = keywordInput.value.trim();
        if (!keyword) {
            keywordInput.focus();
            api.announce("请输入采集关键词", "error");
            return;
        }
        if (!ruleSelect || !ruleSelect.value) {
            api.announce("当前没有可用采集规则", "error");
            return;
        }
        const body = new URLSearchParams();
        body.set("keyword", keyword);
        body.set("rule_id", ruleSelect.value);
        body.set("page", pageInput?.value || "1");
        body.set("page_size", pageSizeInput?.value || "12");
        body.set("_xsrf", api.xsrfToken());
        state.lastRequest = body.toString();
        api.setBusy(button, true, "正在采集…");
        showLoading();
        updatePipeline("result", ["query", "rule"]);
        try {
            const data = await api.fetchJson(form.action, {
                method: "POST",
                headers: {"Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"},
                body: state.lastRequest
            });
            renderResults(Array.isArray(data.items) ? data.items : []);
            api.announce(data.message || `采集任务 #${data.run_id || "-"} 已完成`);
        } catch (error) {
            const message = api.errorMessage(error, "采集请求失败，请检查规则或网络后重试。");
            showError(message);
            api.announce(message, "error");
        } finally {
            api.setBusy(button, false);
        }
    });

    importButton?.addEventListener("click", async () => {
        const ids = Array.from(state.selected);
        if (!ids.length) return;
        api.setBusy(importButton, true, "正在入仓…");
        try {
            const data = await api.fetchJson("/admin/warehouse/import", {
                method: "POST",
                headers: {"Content-Type": "application/json;charset=UTF-8"},
                body: JSON.stringify({result_ids: ids})
            });
            api.announce(data.message || `已保存 ${ids.length} 条结果到数据仓库`);
            updatePipeline("warehouse", ["query", "rule", "result"]);
        } catch (error) {
            api.announce(api.errorMessage(error, "入仓失败，请稍后重试"), "error");
        } finally {
            api.setBusy(importButton, false);
            updateSelection();
        }
    });
})();
