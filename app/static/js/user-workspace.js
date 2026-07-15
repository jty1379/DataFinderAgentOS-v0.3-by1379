(function () {
    "use strict";

    const root = document.querySelector("[data-user-workspace]");
    if (!root) return;

    const $ = (selector, scope = root) => scope.querySelector(selector);
    const $$ = (selector, scope = root) => Array.from(scope.querySelectorAll(selector));
    const rail = $("[data-task-rail]");
    const scrim = $("[data-workspace-scrim]");
    const welcome = $("[data-workspace-welcome]");
    const stream = $("[data-message-stream]");
    const dialogue = $("[data-dialogue-area]");
    const form = $("[data-question-composer]");
    const input = $("[data-question-input]");
    const sendButton = $("[data-send-button]");
    const modelSelect = $("[data-model-select]");
    const title = $("[data-conversation-title]");
    const command = $("[data-employee-command]");
    const commandButtons = $$("[data-employee-id]", command);
    const activeEmployee = $("[data-active-employee]");
    const activeEmployeeName = $("[data-active-employee-name]");
    const historyList = $("[data-history-list]");
    const historyEmpty = $("[data-history-empty]");
    let conversationId = null;
    let employeeId = null;
    let employeeMention = "";
    let commandIndex = 0;
    let loading = false;

    function xsrfToken() {
        const item = document.cookie.split("; ").find((part) => part.startsWith("_xsrf="));
        return item ? decodeURIComponent(item.split("=").slice(1).join("=")) : "";
    }

    function closeRail() {
        rail.classList.remove("open");
        scrim.classList.remove("show");
    }
    $("[data-rail-open]").addEventListener("click", () => {
        rail.classList.add("open");
        scrim.classList.add("show");
    });
    $("[data-rail-close]").addEventListener("click", closeRail);
    scrim.addEventListener("click", closeRail);

    function setCommandVisible(visible) {
        command.hidden = !visible || commandButtons.length === 0;
        if (!command.hidden) setCommandIndex(0);
    }

    function setCommandIndex(index) {
        if (!commandButtons.length) return;
        commandIndex = (index + commandButtons.length) % commandButtons.length;
        commandButtons.forEach((button, current) => button.classList.toggle("active", current === commandIndex));
        commandButtons[commandIndex].scrollIntoView({block: "nearest"});
    }

    function selectEmployee(button, keepQuestion = false) {
        employeeId = Number(button.dataset.employeeId || button.dataset.starterEmployee || 0) || null;
        employeeMention = button.dataset.employeeMention || button.dataset.starterMention || "";
        activeEmployee.hidden = !employeeId;
        activeEmployeeName.textContent = employeeMention ? `@${employeeMention}` : "";
        if (!keepQuestion) {
            const text = input.value.replace(/^\s*[/@][^\s]*\s*/, "");
            input.value = `@${employeeMention} ${text}`;
            resizeInput();
        }
        setCommandVisible(false);
        input.focus();
    }

    commandButtons.forEach((button) => button.addEventListener("click", () => selectEmployee(button)));
    $$('[data-starter-employee]').forEach((button) => {
        button.addEventListener("click", () => {
            selectEmployee(button);
            input.scrollIntoView({behavior: "smooth", block: "center"});
        });
    });
    $("[data-clear-employee]").addEventListener("click", () => {
        employeeId = null;
        employeeMention = "";
        activeEmployee.hidden = true;
        input.value = input.value.replace(/^\s*[/@][^\s]+\s*/, "");
        input.focus();
    });

    function resizeInput() {
        input.style.height = "auto";
        input.style.height = `${Math.min(180, input.scrollHeight)}px`;
    }

    input.addEventListener("input", () => {
        resizeInput();
        const trimmed = input.value.trimStart();
        setCommandVisible(trimmed === "@" || trimmed === "/" || /^[/@][^\s]*$/.test(trimmed));
        if (employeeId && !trimmed.startsWith(`@${employeeMention}`) && !trimmed.startsWith(`/${employeeMention}`)) {
            employeeId = null;
            employeeMention = "";
            activeEmployee.hidden = true;
        }
    });
    input.addEventListener("keydown", (event) => {
        if (!command.hidden) {
            if (event.key === "ArrowDown" || event.key === "ArrowUp") {
                event.preventDefault();
                setCommandIndex(commandIndex + (event.key === "ArrowDown" ? 1 : -1));
                return;
            }
            if (event.key === "Enter") {
                event.preventDefault();
                selectEmployee(commandButtons[commandIndex]);
                return;
            }
            if (event.key === "Escape") {
                event.preventDefault();
                setCommandVisible(false);
                return;
            }
        }
        if (event.key === "Enter" && !event.shiftKey) {
            event.preventDefault();
            form.requestSubmit();
        }
    });

    function beginMessages() {
        welcome.hidden = true;
        stream.classList.add("active");
    }

    function textNode(tag, className, value) {
        const node = document.createElement(tag);
        if (className) node.className = className;
        node.textContent = value;
        return node;
    }

    function weatherCard(data) {
        const card = document.createElement("div");
        card.className = "weather-card";
        const head = document.createElement("div"); head.className = "weather-head";
        const place = document.createElement("div");
        place.append(textNode("h3", "", data.location || "天气查询"), textNode("p", "", data.region || `数据来源：${data.source || "wttr.in"}`));
        head.append(place, textNode("div", "weather-temp", `${data.temperature_c ?? "--"}°C`));
        card.append(head, textNode("p", "weather-summary", data.summary || "暂无天气描述"));
        const facts = document.createElement("div"); facts.className = "weather-facts";
        [["体感", `${data.feels_like_c ?? "--"}°C`], ["湿度", `${data.humidity ?? "--"}%`], ["风况", data.wind || "--"], ["能见度", `${data.visibility_km ?? "--"} km`]].forEach(([label, value]) => {
            const item = textNode("span", "", label); item.append(textNode("b", "", value)); facts.append(item);
        });
        card.append(facts);
        if (Array.isArray(data.forecast) && data.forecast.length) {
            const forecast = document.createElement("div"); forecast.className = "weather-forecast";
            data.forecast.forEach((day) => {
                const item = document.createElement("div");
                item.append(textNode("b", "", day.date || "--"), textNode("small", "", `${day.min_c ?? "--"}~${day.max_c ?? "--"}°C · ${day.description || "暂无描述"}`)); forecast.append(item);
            });
            card.append(forecast);
        }
        return card;
    }

    function chartCanvas(spec) {
        const canvas = document.createElement("canvas");
        canvas.className = "analysis-canvas";
        canvas.setAttribute("role", "img");
        canvas.setAttribute("aria-label", spec.title || "数据图表");
        const draw = () => {
            const width = Math.max(280, canvas.clientWidth || 560);
            const height = 220;
            const ratio = window.devicePixelRatio || 1;
            canvas.width = width * ratio; canvas.height = height * ratio;
            const ctx = canvas.getContext("2d"); ctx.scale(ratio, ratio);
            ctx.clearRect(0, 0, width, height);
            ctx.font = "12px Microsoft YaHei"; ctx.lineWidth = 2;
            const values = Array.isArray(spec.data) ? spec.data : [];
            if (!values.length) {
                ctx.fillStyle = "#637c8d"; ctx.fillText("暂无可展示数据", 16, 32); return;
            }
            if (spec.type === "donut") {
                const total = values.reduce((sum, item) => sum + Number(item.value || 0), 0) || 1;
                const colors = ["#246b9e", "#c7d6df", "#d97706", "#2f7d5d"];
                let angle = -Math.PI / 2;
                values.forEach((item, index) => {
                    const next = angle + Math.PI * 2 * Number(item.value || 0) / total;
                    ctx.beginPath(); ctx.arc(width / 2, 91, 64, angle, next);
                    ctx.strokeStyle = colors[index % colors.length]; ctx.lineWidth = 22; ctx.stroke(); angle = next;
                });
                ctx.fillStyle = "#152b3b"; ctx.font = "700 20px Microsoft YaHei";
                ctx.textAlign = "center"; ctx.fillText(String(total), width / 2, 98);
                ctx.font = "11px Microsoft YaHei"; ctx.fillStyle = "#637c8d";
                values.forEach((item, i) => ctx.fillText(`${item.label} ${item.value}`, width / 2, 181 + i * 17));
                return;
            }
            const pad = {left: 42, right: 14, top: 18, bottom: 42};
            const chartW = width - pad.left - pad.right, chartH = height - pad.top - pad.bottom;
            const max = Math.max(1, ...values.map((item) => Number(item.value || 0)));
            ctx.strokeStyle = "#d7e1e8"; ctx.lineWidth = 1;
            for (let i = 0; i <= 4; i += 1) {
                const y = pad.top + chartH * i / 4;
                ctx.beginPath(); ctx.moveTo(pad.left, y); ctx.lineTo(width - pad.right, y); ctx.stroke();
            }
            ctx.textAlign = "center"; ctx.font = "10px Microsoft YaHei";
            if (spec.type === "bar") {
                const slot = chartW / values.length, barW = Math.min(48, slot * .58);
                values.forEach((item, index) => {
                    const h = chartH * Number(item.value || 0) / max;
                    const x = pad.left + slot * index + (slot - barW) / 2;
                    ctx.fillStyle = "#246b9e"; ctx.fillRect(x, pad.top + chartH - h, barW, h);
                    ctx.fillStyle = "#152b3b"; ctx.fillText(String(item.value), x + barW / 2, pad.top + chartH - h - 6);
                    ctx.fillStyle = "#637c8d"; ctx.fillText(String(item.label).slice(0, 8), x + barW / 2, height - 16);
                });
            } else {
                const step = values.length > 1 ? chartW / (values.length - 1) : 0;
                ctx.strokeStyle = "#246b9e"; ctx.lineWidth = 2; ctx.beginPath();
                values.forEach((item, index) => {
                    const x = pad.left + step * index;
                    const y = pad.top + chartH - chartH * Number(item.value || 0) / max;
                    index ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
                });
                ctx.stroke();
                values.forEach((item, index) => {
                    const x = pad.left + step * index;
                    const y = pad.top + chartH - chartH * Number(item.value || 0) / max;
                    ctx.fillStyle = "#fff"; ctx.beginPath(); ctx.arc(x, y, 4, 0, Math.PI * 2); ctx.fill();
                    ctx.strokeStyle = "#246b9e"; ctx.stroke();
                    ctx.fillStyle = "#637c8d"; ctx.fillText(String(item.label).slice(5), x, height - 16);
                });
            }
        };
        requestAnimationFrame(draw);
        return canvas;
    }

    function graphCanvas(spec) {
        const canvas = document.createElement("canvas"); canvas.className = "analysis-canvas";
        canvas.setAttribute("role", "img"); canvas.setAttribute("aria-label", spec.title || "关系图谱");
        requestAnimationFrame(() => {
            const width = Math.max(280, canvas.clientWidth || 560), height = 250, ratio = window.devicePixelRatio || 1;
            canvas.width = width * ratio; canvas.height = height * ratio;
            const ctx = canvas.getContext("2d"); ctx.scale(ratio, ratio);
            const nodes = Array.isArray(spec.nodes) ? spec.nodes.slice(0, 24) : [];
            const edges = Array.isArray(spec.edges) ? spec.edges : [];
            const sourceNodes = nodes.filter((node) => node.group === "source");
            const itemNodes = nodes.filter((node) => node.group !== "source");
            const positions = new Map();
            sourceNodes.forEach((node, i) => positions.set(node.id, {x: width * .22, y: 34 + i * Math.min(44, 180 / Math.max(1, sourceNodes.length - 1))}));
            itemNodes.forEach((node, i) => positions.set(node.id, {x: width * .72, y: 24 + i * Math.min(28, 205 / Math.max(1, itemNodes.length - 1))}));
            ctx.strokeStyle = "rgba(99,124,141,.45)"; ctx.lineWidth = 1;
            edges.forEach((edge) => { const a = positions.get(edge.source), b = positions.get(edge.target); if (!a || !b) return; ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke(); });
            nodes.forEach((node) => {
                const p = positions.get(node.id); if (!p) return;
                ctx.fillStyle = node.group === "source" ? "#246b9e" : "#d97706";
                ctx.beginPath(); ctx.arc(p.x, p.y, node.group === "source" ? 7 : 5, 0, Math.PI * 2); ctx.fill();
                ctx.fillStyle = "#152b3b"; ctx.font = "10px Microsoft YaHei";
                ctx.textAlign = p.x < width / 2 ? "right" : "left";
                ctx.fillText(String(node.label).slice(0, 16), p.x + (p.x < width / 2 ? -10 : 10), p.y + 3);
            });
        });
        return canvas;
    }

    function analysisCard(data) {
        const card = document.createElement("section"); card.className = "analysis-card";
        card.append(textNode("p", "analysis-kicker", "数据仓库 · 安全只读分析"), textNode("h3", "", data.title || "问数结果"), textNode("p", "analysis-summary", data.narrative || ""));
        (data.visualizations || []).forEach((spec) => {
            const panel = document.createElement("section"); panel.className = "analysis-panel";
            panel.append(textNode("h4", "", spec.title || "数据视图"));
            if (spec.type === "kpi") {
                const grid = document.createElement("div"); grid.className = "analysis-kpis";
                (spec.data || []).forEach((item) => { const cell = document.createElement("div"); cell.append(textNode("b", "", item.value), textNode("span", "", item.label)); grid.append(cell); }); panel.append(grid);
            } else if (spec.type === "table") {
                const wrap = document.createElement("div"); wrap.className = "analysis-table-wrap";
                const table = document.createElement("table"), head = document.createElement("thead"), tr = document.createElement("tr");
                (spec.labels || spec.columns || []).forEach((label) => tr.append(textNode("th", "", label))); head.append(tr); table.append(head);
                const body = document.createElement("tbody"); (spec.data || []).forEach((row) => { const line = document.createElement("tr"); (spec.columns || []).forEach((key) => line.append(textNode("td", "", row[key] ?? "--"))); body.append(line); }); table.append(body); wrap.append(table); panel.append(wrap);
            } else if (spec.type === "graph") {
                panel.append(graphCanvas(spec));
                const details = document.createElement("details"); details.append(textNode("summary", "", "查看关系文字列表"));
                const labels = new Map((spec.nodes || []).map((node) => [node.id, node.label]));
                const list = document.createElement("ul"); (spec.edges || []).forEach((edge) => list.append(textNode("li", "", `${labels.get(edge.source) || edge.source} → ${labels.get(edge.target) || edge.target}`))); details.append(list); panel.append(details);
            } else panel.append(chartCanvas(spec));
            card.append(panel);
        });
        card.append(textNode("p", "analysis-source", data.source_note || ""));
        return card;
    }

    function appendMessage(message, temporary = false) {
        beginMessages();
        const wrapper = document.createElement("article");
        wrapper.className = `chat-message ${message.role || "assistant"}`;
        if (temporary) wrapper.dataset.temporary = "1";
        const avatar = textNode("span", "message-avatar", message.role === "user" ? "我" : "DF");
        const content = document.createElement("div"); content.className = `message-content${message.content_type === "error" ? " error" : ""}`;
        if (temporary) {
            const typing = document.createElement("span"); typing.className = "typing-indicator";
            typing.append(document.createElement("i"), document.createElement("i"), document.createElement("i")); content.append(typing);
        } else if (message.content_type === "card") {
            let data = message.metadata && message.metadata.data;
            if (!data) { try { data = JSON.parse(message.content); } catch (_) { data = null; } }
            if (data && data.kind === "weather") content.append(weatherCard(data));
            else if (data && data.kind === "analysis") content.append(analysisCard(data));
            else content.append(textNode("pre", "", JSON.stringify(data || message.content, null, 2)));
        } else {
            content.textContent = message.content || "";
        }
        if (!temporary && message.metadata) {
            const source = message.metadata.employee || message.metadata.model || (message.metadata.data && message.metadata.data.kind === "analysis" ? "问数分析器" : "系统服务");
            const usage = message.metadata.usage || {};
            const elapsed = Number(message.metadata.elapsed_seconds ?? (Number(usage.latency_ms || 0) / 1000)).toFixed(2);
            content.append(textNode("small", "message-meta", `响应 ${elapsed}s · ${Number(usage.total_tokens || 0)} token · 服务：${source}`));
        }
        wrapper.append(avatar, content); stream.append(wrapper);
        dialogue.scrollTop = dialogue.scrollHeight;
        return wrapper;
    }

    function resetWorkspace() {
        conversationId = null; employeeId = null; employeeMention = "";
        activeEmployee.hidden = true; title.textContent = "新建问数任务";
        stream.replaceChildren(); stream.classList.remove("active"); welcome.hidden = false;
        $$(".history-item", historyList).forEach((item) => item.classList.remove("active"));
        input.value = ""; resizeInput(); input.focus(); closeRail();
    }
    $("[data-new-conversation]").addEventListener("click", resetWorkspace);

    function addOrUpdateHistory(conversation) {
        if (!conversation) return;
        historyEmpty.classList.add("hidden");
        let button = $(`[data-conversation-id="${conversation.id}"]`, historyList);
        if (!button) {
            button = document.createElement("button"); button.type = "button"; button.className = "history-item"; button.dataset.conversationId = conversation.id;
            button.innerHTML = '<i class="layui-icon layui-icon-file-b"></i><span><b></b><small>刚刚 · 2 条</small></span>';
            button.addEventListener("click", () => loadConversation(button)); historyList.prepend(button);
        }
        $("b", button).textContent = conversation.title;
        $$(".history-item", historyList).forEach((item) => item.classList.toggle("active", item === button));
        title.textContent = conversation.title;
    }

    async function loadConversation(button) {
        if (loading) return;
        closeRail();
        $$(".history-item", historyList).forEach((item) => item.classList.toggle("active", item === button));
        stream.replaceChildren(); beginMessages();
        appendMessage({role: "assistant"}, true);
        try {
            const response = await fetch(`/api/conversations/${button.dataset.conversationId}`, {headers: {"Accept": "application/json"}});
            const data = await response.json();
            if (!response.ok || !data.ok) throw new Error(data.message || "加载会话失败");
            stream.replaceChildren();
            conversationId = data.conversation.id; title.textContent = data.conversation.title;
            modelSelect.value = data.conversation.model_id || modelSelect.value;
            employeeId = data.conversation.employee_id || null;
            employeeMention = ""; activeEmployee.hidden = true;
            data.messages.forEach((message) => appendMessage(message));
        } catch (error) {
            stream.replaceChildren(); appendMessage({role: "assistant", content_type: "error", content: error.message});
        }
    }
    $$(".history-item", historyList).forEach((button) => button.addEventListener("click", () => loadConversation(button)));

    form.addEventListener("submit", async (event) => {
        event.preventDefault();
        const message = input.value.trim();
        if (!message || loading) return;
        loading = true; sendButton.disabled = true; sendButton.querySelector("span").textContent = "处理中";
        appendMessage({role: "user", content_type: "text", content: message});
        const pending = appendMessage({role: "assistant"}, true);
        input.value = ""; resizeInput(); setCommandVisible(false);
        try {
            const response = await fetch("/api/chat/stream", {
                method: "POST",
                headers: {"Content-Type": "application/json", "Accept": "text/event-stream", "X-Xsrftoken": xsrfToken()},
                body: JSON.stringify({message, conversation_id: conversationId, model_id: modelSelect.value || null, employee_id: employeeId})
            });
            if (!response.ok || !response.body) throw new Error("问数流式服务暂时不可用");
            const reader = response.body.getReader(), decoder = new TextDecoder("utf-8");
            let buffer = "", reply = {role: "assistant", content_type: "text", content: "", metadata: {}};
            let streamError = null;
            while (true) {
                const chunk = await reader.read();
                buffer += decoder.decode(chunk.value || new Uint8Array(), {stream: !chunk.done});
                const blocks = buffer.split(/\r?\n\r?\n/); buffer = blocks.pop() || "";
                blocks.forEach((block) => {
                    let eventName = "message", payloadText = "";
                    block.split(/\r?\n/).forEach((line) => { if (line.startsWith("event:")) eventName = line.slice(6).trim(); if (line.startsWith("data:")) payloadText += line.slice(5).trim(); });
                    if (!payloadText) return;
                    let data; try { data = JSON.parse(payloadText); } catch (_) { return; }
                    if (eventName === "delta") {
                        reply.content += data.text || "";
                        const target = pending.querySelector(".message-content"); target.classList.remove("error"); target.textContent = reply.content;
                    } else if (eventName === "message") reply = data;
                    else if (eventName === "usage") reply.metadata = Object.assign({}, reply.metadata || {}, {usage: {total_tokens: data.total_tokens || 0}, elapsed_seconds: data.elapsed_seconds || 0, employee: data.source});
                    else if (eventName === "conversation") { conversationId = data.id; addOrUpdateHistory(data); }
                    else if (eventName === "error") { if (data.conversation_id) conversationId = data.conversation_id; streamError = new Error(data.message || "问数服务暂时不可用"); }
                });
                if (chunk.done) break;
            }
            pending.remove();
            if (streamError) throw streamError;
            appendMessage(reply);
        } catch (error) {
            pending.remove(); appendMessage({role: "assistant", content_type: "error", content: error.message});
        } finally {
            loading = false; sendButton.disabled = false; sendButton.querySelector("span").textContent = "发送"; input.focus();
        }
    });
})();
