/* 管理端「对话详情」消息渲染与回放。
 *
 * - 复用 window.DataFinderCards / window.DataFinderMarkdown 渲染卡片与文本，
 *   不再直接显示原始 JSON。
 * - 默认「回放」模式：按时间顺序逐条呈现消息（带淡入 + 自动滚动）；
 *   另提供「直接展示」模式一次性展示全部。用户选择记忆在 localStorage。 */
(function () {
    "use strict";

    const root = document.querySelector("[data-session-replay]");
    if (!root) return;

    const dataEl = document.getElementById("session-messages-data");
    let messages = [];
    try {
        messages = JSON.parse((dataEl && dataEl.textContent) || "[]");
    } catch (_) {
        messages = [];
    }
    if (!Array.isArray(messages)) messages = [];

    const listEl = root.querySelector("[data-replay-list]");
    const emptyEl = root.querySelector("[data-replay-empty]");
    const controlsEl = root.querySelector("[data-replay-controls]");
    const progressEl = root.querySelector("[data-replay-progress]");
    const speedEl = root.querySelector("[data-replay-speed]");
    const modeButtons = Array.from(root.querySelectorAll("[data-replay-mode]"));
    const toggleBtn = root.querySelector('[data-replay-action="toggle"]');
    const restartBtn = root.querySelector('[data-replay-action="restart"]');

    const cards = window.DataFinderCards;
    const markdown = window.DataFinderMarkdown;
    const RISK_LABELS = {low: "低", medium: "中", high: "高", critical: "严重"};
    const STORAGE_KEY = "admin-session-replay-mode";

    let mode = localStorage.getItem(STORAGE_KEY) === "all" ? "all" : "replay";
    let index = 0;
    let playing = false;
    let timer = null;

    function delay() {
        const value = Number(speedEl && speedEl.value);
        return Number.isFinite(value) && value > 0 ? value : 900;
    }

    function contentNode(message) {
        if (message.content_type === "card") {
            let data = message.metadata && message.metadata.data;
            if (!data) {
                try {
                    data = JSON.parse(message.content);
                } catch (_) {
                    data = {type: "text", data: {text: message.content || "暂无卡片数据"}};
                }
            }
            if (cards && typeof cards.render === "function") return cards.render(data);
        }
        const wrap = document.createElement("div");
        if (markdown && typeof markdown.render === "function" && message.content_type !== "error") {
            wrap.append(markdown.render(message.content || ""));
        } else {
            wrap.textContent = message.content || "";
        }
        return wrap;
    }

    function buildMessage(message) {
        const article = document.createElement("article");
        article.className = "session-message " + (message.role === "user" ? "user" : message.content_type === "error" ? "assistant error" : "assistant");

        const header = document.createElement("header");
        const who = document.createElement("b");
        who.textContent = message.role === "user" ? "用户" : "系统回复";
        const time = document.createElement("time");
        time.textContent = message.created_at || "";
        header.append(who, time);

        const body = document.createElement("div");
        body.className = "session-message-content";
        body.append(contentNode(message));

        const footer = document.createElement("footer");
        [
            "类型 " + (message.content_type || "text"),
            "风险 " + (RISK_LABELS[message.risk_level] || "低"),
            (message.latency_ms || 0) + " ms",
            (message.token_count || 0) + " tokens",
        ].forEach((text) => {
            const span = document.createElement("span");
            span.textContent = text;
            footer.append(span);
        });
        if (message.matched_words && message.matched_words !== "[]") {
            const span = document.createElement("span");
            span.textContent = "命中 " + message.matched_words;
            footer.append(span);
        }

        article.append(header, body, footer);
        return article;
    }

    function updateProgress() {
        if (progressEl) progressEl.textContent = index + " / " + messages.length;
    }

    function updateToggleLabel() {
        if (!toggleBtn) return;
        // 播放中显示“暂停”；暂停或播完都显示“播放”（播完后再点会从头重放）。
        toggleBtn.textContent = playing ? "暂停" : "播放";
    }

    function stopTimer() {
        if (timer) {
            clearTimeout(timer);
            timer = null;
        }
    }

    function clearList() {
        stopTimer();
        listEl.innerHTML = "";
        index = 0;
    }

    function appendNext() {
        if (index >= messages.length) {
            playing = false;
            updateToggleLabel();
            updateProgress();
            return;
        }
        const element = buildMessage(messages[index]);
        element.classList.add("replay-enter");
        listEl.append(element);
        requestAnimationFrame(() => element.classList.add("replay-enter-active"));
        element.scrollIntoView({behavior: "smooth", block: "nearest"});
        index += 1;
        updateProgress();
        updateToggleLabel();
        if (playing && index < messages.length) {
            timer = setTimeout(appendNext, delay());
        } else {
            playing = false;
            updateToggleLabel();
        }
    }

    function play() {
        if (!messages.length) return;
        if (index >= messages.length) clearList();
        playing = true;
        updateToggleLabel();
        appendNext();
    }

    function pause() {
        playing = false;
        stopTimer();
        updateToggleLabel();
    }

    function renderAll() {
        clearList();
        const fragment = document.createDocumentFragment();
        messages.forEach((message) => fragment.append(buildMessage(message)));
        listEl.append(fragment);
        index = messages.length;
        updateProgress();
    }

    function applyMode(next, options) {
        mode = next === "all" ? "all" : "replay";
        localStorage.setItem(STORAGE_KEY, mode);
        modeButtons.forEach((button) => button.classList.toggle("active", button.dataset.replayMode === mode));
        if (controlsEl) controlsEl.hidden = mode !== "replay";
        if (mode === "all") {
            pause();
            renderAll();
        } else {
            clearList();
            updateProgress();
            updateToggleLabel();
            if (!options || options.autoplay !== false) play();
        }
    }

    if (!messages.length) {
        if (emptyEl) emptyEl.hidden = false;
        if (controlsEl) controlsEl.hidden = true;
        modeButtons.forEach((button) => (button.disabled = true));
        updateProgress();
        return;
    }

    modeButtons.forEach((button) => {
        button.addEventListener("click", () => {
            if (button.dataset.replayMode === mode) return;
            applyMode(button.dataset.replayMode);
        });
    });
    if (toggleBtn) {
        toggleBtn.addEventListener("click", () => {
            if (index >= messages.length) {
                clearList();
                updateProgress();
                play();
            } else if (playing) {
                pause();
            } else {
                play();
            }
        });
    }
    if (restartBtn) {
        restartBtn.addEventListener("click", () => {
            clearList();
            updateProgress();
            play();
        });
    }

    applyMode(mode);
})();
