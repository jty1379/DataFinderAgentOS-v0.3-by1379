(function () {
    "use strict";

    const app = window.DataFinderApp;
    if (!app) throw new Error("DataFinderApp must be loaded before DataFinderSSE");

    const EVENTS = new Set(["meta", "delta", "card", "audio", "error", "done"]);

    function parseBlock(block) {
        let event = "delta";
        let id = "";
        const data = [];
        block.split(/\r?\n/).forEach((line) => {
            if (!line || line.startsWith(":")) return;
            const separator = line.indexOf(":");
            const field = separator < 0 ? line : line.slice(0, separator);
            const value = separator < 0 ? "" : line.slice(separator + 1).replace(/^ /, "");
            if (field === "event") event = value;
            else if (field === "data") data.push(value);
            else if (field === "id") id = value;
        });
        if (!data.length) return null;
        if (!EVENTS.has(event)) {
            throw new app.RequestError(`服务返回了未约定的 SSE 事件：${event}`, {code: "INVALID_SSE_EVENT"});
        }
        const raw = data.join("\n");
        if (raw === "[DONE]") return {event: "done", data: {}, id};
        try {
            return {event, data: JSON.parse(raw), id};
        } catch (error) {
            throw new app.RequestError("SSE 事件数据不是有效 JSON", {code: "INVALID_SSE_DATA", cause: error});
        }
    }

    async function stream(url, options = {}) {
        const response = await app.fetchResponse(url, {
            ...options,
            accept: "text/event-stream",
            stream: true,
            timeoutMs: options.connectTimeoutMs ?? 30000
        });
        if (!response.ok || !response.body) {
            const payload = await app.responseData(response);
            throw app.errorFromPayload(payload, response);
        }
        const contentType = response.headers.get("content-type") || "";
        if (!contentType.includes("text/event-stream")) {
            throw new app.RequestError("服务未返回 SSE 数据流", {
                code: "INVALID_SSE_RESPONSE",
                status: response.status,
                requestId: response.headers.get("X-Request-ID") || ""
            });
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder("utf-8");
        let buffer = "";
        let completed = false;
        const dispatch = async (block) => {
            const item = parseBlock(block);
            if (!item) return;
            if (item.event === "error") {
                const detail = item.data?.error || item.data || {};
                throw new app.RequestError(detail.message || detail.error || "流式服务执行失败", {
                    code: detail.code || "SSE_ERROR",
                    requestId: detail.request_id || item.data?.request_id || "",
                    details: detail
                });
            }
            if (item.event === "done") completed = true;
            if (typeof options.onEvent === "function") await options.onEvent(item);
        };

        try {
            while (true) {
                const chunk = await reader.read();
                buffer += decoder.decode(chunk.value || new Uint8Array(), {stream: !chunk.done});
                const blocks = buffer.split(/\r?\n\r?\n/);
                buffer = blocks.pop() || "";
                for (const block of blocks) await dispatch(block);
                if (chunk.done) break;
            }
            if (buffer.trim()) await dispatch(buffer);
            if (!completed && !options.allowEarlyClose) {
                throw new app.RequestError("SSE 连接在完成事件前中断", {code: "SSE_INCOMPLETE"});
            }
            return {completed, requestId: response.headers.get("X-Request-ID") || ""};
        } finally {
            if (!completed) reader.cancel().catch(() => {});
            response.dataFinderAbortCleanup?.();
        }
    }

    window.DataFinderSSE = Object.freeze({EVENTS, parseBlock, stream});
})();
