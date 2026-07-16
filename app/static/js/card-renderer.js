(function () {
    "use strict";

    const TYPES = new Set(["text", "kpi", "table", "line_chart", "bar_chart", "pie_chart", "weather", "music", "news", "image", "video"]);

    function node(tag, className = "", text = null) {
        const element = document.createElement(tag);
        if (className) element.className = className;
        if (text !== null && text !== undefined) element.textContent = String(text);
        return element;
    }

    function safeUrl(value) {
        try {
            const url = new URL(String(value || ""), window.location.origin);
            return ["http:", "https:"].includes(url.protocol) ? url.href : "";
        } catch (_) {
            return "";
        }
    }

    function normalize(card) {
        if (!card || typeof card !== "object") return {type: "text", data: {text: String(card ?? "")}};
        if (TYPES.has(card.type)) return {type: card.type, data: card.data && typeof card.data === "object" ? card.data : {text: card.data}};
        if (card.kind === "weather") return {type: "weather", data: card};
        if (card.kind === "music") return {type: "music", data: card};
        if (card.kind === "news") return {type: "news", data: card};
        if (card.kind === "analysis") return {type: "analysis", data: card};
        return {type: "text", data: {text: card.text || card.content || JSON.stringify(card, null, 2)}};
    }

    function weather(data) {
        const card = node("section", "weather-card");
        const head = node("div", "weather-head");
        const place = node("div");
        place.append(node("h3", "", data.location || "天气查询"), node("p", "", data.region || `数据来源：${data.source || "wttr.in"}`));
        head.append(place, node("div", "weather-temp", `${data.temperature_c ?? "--"}°C`));
        card.append(head, node("p", "weather-summary", data.summary || "暂无天气描述"));
        const facts = node("div", "weather-facts");
        [["体感", `${data.feels_like_c ?? "--"}°C`], ["湿度", `${data.humidity ?? "--"}%`], ["风况", data.wind || "--"], ["能见度", `${data.visibility_km ?? "--"} km`]].forEach(([label, value]) => {
            const item = node("span", "", label);
            item.append(node("b", "", value));
            facts.append(item);
        });
        card.append(facts);
        if (Array.isArray(data.forecast) && data.forecast.length) {
            const forecast = node("div", "weather-forecast");
            data.forecast.slice(0, 7).forEach((day) => {
                const item = node("div");
                item.append(node("b", "", day.date || "--"), node("small", "", `${day.min_c ?? "--"}~${day.max_c ?? "--"}°C · ${day.description || "暂无描述"}`));
                forecast.append(item);
            });
            card.append(forecast);
        }
        return card;
    }

    function kpi(data) {
        const grid = node("div", "analysis-kpis");
        const items = Array.isArray(data.items) ? data.items : Array.isArray(data) ? data : [];
        items.forEach((item) => {
            const cell = node("div");
            cell.append(node("b", "", item.value ?? "--"), node("span", "", item.label || item.name || "指标"));
            grid.append(cell);
        });
        return grid;
    }

    function table(data) {
        const columns = Array.isArray(data.columns) ? data.columns : [];
        const rows = Array.isArray(data.items) ? data.items : Array.isArray(data.rows) ? data.rows : [];
        const wrap = node("div", "analysis-table-wrap");
        const element = node("table");
        const head = node("thead");
        const headRow = node("tr");
        columns.forEach((column) => headRow.append(node("th", "", typeof column === "object" ? column.label : column)));
        head.append(headRow);
        const body = node("tbody");
        rows.forEach((row) => {
            const line = node("tr");
            columns.forEach((column) => {
                const key = typeof column === "object" ? column.key : column;
                line.append(node("td", "", row?.[key] ?? "--"));
            });
            body.append(line);
        });
        element.append(head, body);
        wrap.append(element);
        return wrap;
    }

    function chart(type, data) {
        const canvas = node("canvas", "analysis-canvas");
        canvas.setAttribute("role", "img");
        canvas.setAttribute("aria-label", data.title || "数据图表");
        requestAnimationFrame(() => {
            const values = Array.isArray(data.items) ? data.items : Array.isArray(data.data) ? data.data : [];
            const width = Math.max(280, canvas.clientWidth || 560);
            const height = 220;
            const ratio = Math.min(window.devicePixelRatio || 1, 2);
            canvas.width = width * ratio;
            canvas.height = height * ratio;
            const context = canvas.getContext("2d");
            context.scale(ratio, ratio);
            context.font = "12px Microsoft YaHei";
            if (!values.length) {
                context.fillStyle = "#637c8d";
                context.fillText("暂无可展示数据", 16, 32);
                return;
            }
            if (type === "pie_chart") {
                const total = values.reduce((sum, item) => sum + Number(item.value || 0), 0) || 1;
                const colors = ["#246b9e", "#c7d6df", "#d97706", "#2f7d5d", "#7457a8"];
                let angle = -Math.PI / 2;
                values.forEach((item, index) => {
                    const next = angle + Math.PI * 2 * Number(item.value || 0) / total;
                    context.beginPath();
                    context.arc(width / 2, 92, 66, angle, next);
                    context.strokeStyle = colors[index % colors.length];
                    context.lineWidth = 24;
                    context.stroke();
                    angle = next;
                });
                context.textAlign = "center";
                context.fillStyle = "#152b3b";
                context.font = "700 20px Microsoft YaHei";
                context.fillText(String(total), width / 2, 99);
                context.font = "11px Microsoft YaHei";
                values.slice(0, 5).forEach((item, index) => context.fillText(`${item.label || item.name} ${item.value}`, width / 2, 180 + index * 15));
                return;
            }
            const pad = {left: 42, right: 14, top: 18, bottom: 42};
            const chartWidth = width - pad.left - pad.right;
            const chartHeight = height - pad.top - pad.bottom;
            const maximum = Math.max(1, ...values.map((item) => Number(item.value || 0)));
            context.strokeStyle = "#d7e1e8";
            context.lineWidth = 1;
            for (let index = 0; index <= 4; index += 1) {
                const y = pad.top + chartHeight * index / 4;
                context.beginPath();
                context.moveTo(pad.left, y);
                context.lineTo(width - pad.right, y);
                context.stroke();
            }
            context.textAlign = "center";
            context.font = "10px Microsoft YaHei";
            if (type === "bar_chart") {
                const slot = chartWidth / values.length;
                const barWidth = Math.min(48, slot * 0.58);
                values.forEach((item, index) => {
                    const barHeight = chartHeight * Number(item.value || 0) / maximum;
                    const x = pad.left + slot * index + (slot - barWidth) / 2;
                    context.fillStyle = "#246b9e";
                    context.fillRect(x, pad.top + chartHeight - barHeight, barWidth, barHeight);
                    context.fillStyle = "#637c8d";
                    context.fillText(String(item.label || item.name || "").slice(0, 8), x + barWidth / 2, height - 16);
                });
                return;
            }
            const step = values.length > 1 ? chartWidth / (values.length - 1) : 0;
            context.strokeStyle = "#246b9e";
            context.lineWidth = 2;
            context.beginPath();
            values.forEach((item, index) => {
                const x = pad.left + step * index;
                const y = pad.top + chartHeight - chartHeight * Number(item.value || 0) / maximum;
                index ? context.lineTo(x, y) : context.moveTo(x, y);
            });
            context.stroke();
            values.forEach((item, index) => {
                const x = pad.left + step * index;
                const y = pad.top + chartHeight - chartHeight * Number(item.value || 0) / maximum;
                context.fillStyle = "#fff";
                context.beginPath();
                context.arc(x, y, 4, 0, Math.PI * 2);
                context.fill();
                context.strokeStyle = "#246b9e";
                context.stroke();
                context.fillStyle = "#637c8d";
                context.fillText(String(item.label || item.name || "").slice(0, 8), x, height - 16);
            });
        });
        return canvas;
    }

    function media(type, data) {
        const card = node("article", `contract-card ${type}-card`);
        if (type === "music" && Array.isArray(data.tracks)) {
            const heading = node("div", "music-card-heading");
            const title = node("div");
            title.append(
                node("h4", "", data.query ? `站内试听 · ${data.query}` : "站内音乐播放器"),
                node("p", "", data.tracks.length ? `找到 ${data.tracks.length} 首可试听歌曲` : (data.message || "没有找到可试听歌曲"))
            );
            heading.append(title, node("span", "music-source", data.source || "公开试听源"));
            card.append(heading);
            const list = node("div", "music-track-list");
            data.tracks.slice(0, 8).forEach((track, index) => {
                const item = node("section", "music-track");
                const artworkUrl = safeUrl(track.artwork);
                if (artworkUrl) {
                    const artwork = node("img", "music-artwork");
                    artwork.src = artworkUrl;
                    artwork.alt = `${track.title || "歌曲"}封面`;
                    artwork.loading = "lazy";
                    item.append(artwork);
                } else {
                    item.append(node("span", "music-artwork music-artwork-fallback", "♫"));
                }
                const details = node("div", "music-track-main");
                details.append(
                    node("b", "", track.title || `歌曲 ${index + 1}`),
                    node("small", "", [track.artist, track.album].filter(Boolean).join(" · ") || "未标注歌手")
                );
                const previewUrl = safeUrl(track.preview_url || track.url);
                if (previewUrl) {
                    const player = node("audio");
                    player.controls = true;
                    player.preload = "none";
                    player.src = previewUrl;
                    player.addEventListener("play", () => {
                        document.querySelectorAll("audio").forEach((audio) => {
                            if (audio !== player && !audio.paused) audio.pause();
                        });
                    });
                    details.append(player);
                } else {
                    details.append(node("span", "music-unavailable", "当前曲目没有公开试听片段"));
                }
                const actions = node("div", "music-track-actions");
                [[track.store_url, "歌曲页面"], [track.netease_url, "网易云搜索"]].forEach(([value, label]) => {
                    const href = safeUrl(value);
                    if (!href) return;
                    const link = node("a", "", label);
                    link.href = href; link.target = "_blank"; link.rel = "noopener noreferrer";
                    actions.append(link);
                });
                details.append(actions);
                item.append(details);
                list.append(item);
            });
            card.append(list);
            return card;
        }
        if (data.title) card.append(node("h4", "", data.title));
        if (type === "image") {
            const source = safeUrl(data.url || data.src);
            if (source) {
                const image = node("img");
                image.src = source;
                image.alt = data.alt || data.title || "图片结果";
                image.loading = "lazy";
                card.append(image);
            }
        } else if (type === "video" || type === "music") {
            const source = safeUrl(data.url || data.src);
            if (source) {
                const player = node(type === "video" ? "video" : "audio");
                player.controls = true;
                player.preload = "metadata";
                player.src = source;
                card.append(player);
            }
        } else if (type === "news") {
            (data.items || []).slice(0, 10).forEach((item) => {
                const link = node("a", "contract-news-item", item.title || "未命名新闻");
                const href = safeUrl(item.url);
                if (href) {
                    link.href = href;
                    link.target = "_blank";
                    link.rel = "noopener noreferrer";
                }
                card.append(link);
            });
        }
        if (data.description) card.append(node("p", "", data.description));
        return card;
    }

    function analysis(data) {
        const card = node("section", "analysis-card");
        card.append(node("p", "analysis-kicker", "数据仓库 · 安全只读分析"), node("h3", "", data.title || "问数结果"), node("p", "analysis-summary", data.narrative || ""));
        (data.visualizations || []).forEach((spec) => {
            const panel = node("section", "analysis-panel");
            panel.append(node("h4", "", spec.title || "数据视图"));
            if (spec.type === "kpi") panel.append(kpi({items: spec.data || []}));
            else if (spec.type === "table") panel.append(table({columns: (spec.columns || []).map((key, index) => ({key, label: spec.labels?.[index] || key})), items: spec.data || []}));
            else if (spec.type === "graph") {
                const labels = new Map((spec.nodes || []).map((item) => [item.id, item.label]));
                panel.append(table({columns: [{key: "source", label: "来源"}, {key: "target", label: "关联项"}], items: (spec.edges || []).map((edge) => ({source: labels.get(edge.source) || edge.source, target: labels.get(edge.target) || edge.target}))}));
            } else {
                const typeMap = {bar: "bar_chart", line: "line_chart", donut: "pie_chart"};
                panel.append(chart(typeMap[spec.type] || "line_chart", {title: spec.title, items: spec.data || []}));
            }
            card.append(panel);
        });
        if (data.source_note) card.append(node("p", "analysis-source", data.source_note));
        return card;
    }

    function render(card) {
        const normalized = normalize(card);
        const {type, data} = normalized;
        if (type === "analysis") return analysis(data);
        if (type === "weather") return weather(data);
        if (type === "kpi") return kpi(data);
        if (type === "table") return table(data);
        if (["line_chart", "bar_chart", "pie_chart"].includes(type)) return chart(type, data);
        if (["music", "news", "image", "video"].includes(type)) return media(type, data);
        return node("p", "contract-text-card", data.text || data.content || "");
    }

    window.DataFinderCards = Object.freeze({TYPES, normalize, render});
})();
