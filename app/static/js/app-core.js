(function () {
    "use strict";

    const qs = (selector, root = document) => root.querySelector(selector);
    const qsa = (selector, root = document) => Array.from(root.querySelectorAll(selector));

    class RequestError extends Error {
        constructor(message, options = {}) {
            super(message || "请求失败");
            this.name = "RequestError";
            this.code = options.code || "REQUEST_FAILED";
            this.status = Number(options.status) || 0;
            this.requestId = options.requestId || "";
            this.details = options.details || null;
            this.cause = options.cause;
        }
    }

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
        return qs("input[name='_xsrf']")?.value || cookieValue("_xsrf");
    }

    function errorFromPayload(payload, response) {
        const standard = payload && typeof payload.error === "object" ? payload.error : {};
        const message = standard.message || payload?.message || `请求失败（HTTP ${response.status}）`;
        return new RequestError(message, {
            code: standard.code || `HTTP_${response.status}`,
            status: response.status,
            requestId: standard.request_id || payload?.request_id || response.headers.get("X-Request-ID") || "",
            details: standard.details || null
        });
    }

    async function responseData(response) {
        const type = response.headers.get("content-type") || "";
        const text = await response.text();
        if (!text) return {};
        if (type.includes("json") || /^[\[{]/.test(text.trim())) {
            try {
                return JSON.parse(text);
            } catch (error) {
                throw new RequestError("服务返回了无法解析的数据", {
                    code: "INVALID_RESPONSE",
                    status: response.status,
                    requestId: response.headers.get("X-Request-ID") || "",
                    cause: error
                });
            }
        }
        return {message: text};
    }

    function requestOptions(options = {}) {
        const headers = new Headers(options.headers || {});
        headers.set("Accept", options.accept || "application/json");
        const method = String(options.method || "GET").toUpperCase();
        if (!new Set(["GET", "HEAD", "OPTIONS"]).has(method)) {
            const token = xsrfToken();
            if (token && !headers.has("X-Xsrftoken")) headers.set("X-Xsrftoken", token);
        }
        let body = options.body;
        if (options.json !== undefined) {
            headers.set("Content-Type", "application/json;charset=UTF-8");
            body = JSON.stringify(options.json);
        }
        return {headers, method, body};
    }

    async function fetchResponse(url, options = {}) {
        const normalized = requestOptions(options);
        const timeoutMs = Math.max(0, Number(options.timeoutMs ?? 30000));
        const controller = new AbortController();
        const abortFromParent = () => controller.abort(options.signal?.reason);
        if (options.signal) {
            if (options.signal.aborted) abortFromParent();
            else options.signal.addEventListener("abort", abortFromParent, {once: true});
        }
        const timer = timeoutMs ? window.setTimeout(() => controller.abort("timeout"), timeoutMs) : null;
        try {
            const response = await fetch(url, {
                method: normalized.method,
                headers: normalized.headers,
                body: normalized.body,
                signal: controller.signal,
                credentials: options.credentials || "same-origin",
                cache: options.cache || "no-store"
            });
            if (options.stream && options.signal) {
                Object.defineProperty(response, "dataFinderAbortCleanup", {
                    value: () => options.signal.removeEventListener("abort", abortFromParent)
                });
            }
            return response;
        } catch (error) {
            if (error.name === "AbortError") {
                if (options.signal?.aborted) throw error;
                throw new RequestError("请求超时，请检查网络后重试", {code: "REQUEST_TIMEOUT", cause: error});
            }
            throw new RequestError("网络连接失败，请检查网络后重试", {code: "NETWORK_ERROR", cause: error});
        } finally {
            if (timer) window.clearTimeout(timer);
            if (!options.stream) options.signal?.removeEventListener("abort", abortFromParent);
        }
    }

    async function request(url, options = {}) {
        const response = await fetchResponse(url, options);
        const payload = await responseData(response);
        if (!response.ok || payload?.success === false || payload?.ok === false) {
            throw errorFromPayload(payload, response);
        }
        if (payload?.success === true && payload.data && typeof payload.data === "object" && !Array.isArray(payload.data)) {
            return {...payload.data, success: true, message: payload.message || "ok", request_id: payload.request_id || ""};
        }
        return payload;
    }

    function announce(message, level = "info", options = {}) {
        const text = String(message || "操作完成");
        const hasLayer = Boolean(window.layui && window.layui.layer);
        const toast = qs("#app-toast");
        if (toast) {
            toast.textContent = text;
            toast.dataset.level = level;
            toast.setAttribute("role", level === "error" ? "alert" : "status");
            window.clearTimeout(announce.timer);
            if (hasLayer) toast.classList.remove("show");
            else {
                toast.classList.add("show");
                announce.timer = window.setTimeout(() => toast.classList.remove("show"), options.duration || 3600);
            }
        }
        if (hasLayer) {
            const icons = {success: 1, error: 2, warning: 0};
            window.layui.layer.msg(text, {offset: "30px", time: options.duration || 2800, icon: icons[level]});
        }
    }

    function setBusy(button, busy, label = "处理中…") {
        if (!button) return;
        if (busy) {
            if (!button.dataset.originalHtml) button.dataset.originalHtml = button.innerHTML;
            button.setAttribute("aria-busy", "true");
            button.disabled = true;
            const labelNode = document.createElement("span");
            labelNode.textContent = label;
            button.replaceChildren(labelNode);
            return;
        }
        button.removeAttribute("aria-busy");
        button.disabled = false;
        if (button.dataset.originalHtml) button.innerHTML = button.dataset.originalHtml;
    }

    function escapeHtml(value) {
        const node = document.createElement("div");
        node.textContent = value == null ? "" : String(value);
        return node.innerHTML;
    }

    function errorMessage(error, fallback = "操作失败，请稍后重试") {
        if (error instanceof RequestError && error.requestId) return `${error.message}（请求编号：${error.requestId}）`;
        return error?.message || fallback;
    }

    window.DataFinderApp = Object.freeze({
        RequestError,
        announce,
        cookieValue,
        errorFromPayload,
        errorMessage,
        escapeHtml,
        fetchResponse,
        qs,
        qsa,
        request,
        responseData,
        setBusy,
        xsrfToken
    });
})();
