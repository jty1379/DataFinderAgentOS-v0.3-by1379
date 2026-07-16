(function () {
    "use strict";

    const qs = (selector, root = document) => root.querySelector(selector);
    const qsa = (selector, root = document) => Array.from(root.querySelectorAll(selector));

    function cookieValue(name) {
        const prefix = `${name}=`;
        const item = document.cookie.split(";").map((part) => part.trim()).find((part) => part.startsWith(prefix));
        if (!item) return "";
        try {
            return decodeURIComponent(item.slice(prefix.length));
        } catch (_) {
            return item.slice(prefix.length);
        }
    }

    function xsrfToken() {
        const field = qs("input[name='_xsrf']");
        return field ? field.value : cookieValue("_xsrf");
    }

    function announce(message, level = "info") {
        const hasLayer = Boolean(window.layui && window.layui.layer);
        const toast = qs("#app-toast");
        if (toast) {
            toast.textContent = message;
            toast.setAttribute("role", level === "error" ? "alert" : "status");
            window.clearTimeout(announce.timer);
            if (hasLayer) {
                toast.classList.remove("show");
            } else {
                toast.classList.add("show");
                announce.timer = window.setTimeout(() => toast.classList.remove("show"), 3600);
            }
        }
        if (hasLayer) {
            window.layui.layer.msg(message, {offset: "30px", time: 2600, icon: level === "error" ? 2 : undefined});
        }
    }

    function setBusy(button, busy, label = "处理中…") {
        if (!button) return;
        if (busy) {
            if (!button.dataset.originalHtml) button.dataset.originalHtml = button.innerHTML;
            button.setAttribute("aria-busy", "true");
            button.disabled = true;
            const textNode = document.createElement("span");
            textNode.textContent = label;
            button.replaceChildren(textNode);
            return;
        }
        button.removeAttribute("aria-busy");
        button.disabled = false;
        if (button.dataset.originalHtml) button.innerHTML = button.dataset.originalHtml;
    }

    async function responseData(response) {
        const type = response.headers.get("content-type") || "";
        if (type.includes("application/json")) return response.json();
        const text = await response.text();
        try {
            return JSON.parse(text);
        } catch (_) {
            return {ok: response.ok, message: text || `请求失败（HTTP ${response.status}）`};
        }
    }

    async function fetchJson(url, options = {}) {
        const headers = new Headers(options.headers || {});
        headers.set("X-Xsrftoken", xsrfToken());
        headers.set("Accept", "application/json");
        const timeoutMs = Number(options.timeoutMs) || 30000;
        const controller = options.signal ? null : new AbortController();
        const timer = controller ? window.setTimeout(() => controller.abort(), timeoutMs) : null;
        const requestOptions = Object.assign({}, options, {headers, signal: options.signal || controller.signal});
        delete requestOptions.timeoutMs;
        try {
            const response = await fetch(url, requestOptions);
            const data = await responseData(response);
            if (!response.ok || data.ok === false) {
                throw new Error(data.message || `请求失败（HTTP ${response.status}）`);
            }
            return data;
        } catch (error) {
            if (error.name === "AbortError" && controller) throw new Error("请求超时，请检查网络后重试");
            throw error;
        } finally {
            if (timer) window.clearTimeout(timer);
        }
    }

    function escapeHtml(value) {
        const node = document.createElement("div");
        node.textContent = value == null ? "" : String(value);
        return node.innerHTML;
    }

    qsa("[data-reserved-action]").forEach((button) => {
        button.addEventListener("click", () => announce(button.dataset.reservedAction));
    });

    const accountMenu = qs(".admin-account-menu");
    if (accountMenu) {
        document.addEventListener("click", (event) => {
            if (!accountMenu.contains(event.target)) accountMenu.removeAttribute("open");
        });
        document.addEventListener("keydown", (event) => {
            if (event.key === "Escape") accountMenu.removeAttribute("open");
        });
    }

    window.DataFinderAdmin = Object.freeze({
        announce,
        escapeHtml,
        fetchJson,
        qs,
        qsa,
        responseData,
        setBusy,
        xsrfToken
    });
})();
