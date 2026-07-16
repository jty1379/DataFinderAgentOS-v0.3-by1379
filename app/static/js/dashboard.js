(function () {
    "use strict";

    const app = window.DataFinderApp;
    const canvas = document.querySelector("#query-trend-chart");
    if (!app || !canvas) return;

    function drawSeries(context, points, color, dashed) {
        if (!points.length) return;
        context.save();
        context.strokeStyle = color;
        context.lineWidth = 2;
        if (dashed) context.setLineDash([6, 5]);
        context.beginPath();
        points.forEach(([x, y], index) => index ? context.lineTo(x, y) : context.moveTo(x, y));
        context.stroke();
        points.forEach(([x, y]) => {
            context.beginPath();
            context.fillStyle = "#0d2439";
            context.strokeStyle = color;
            context.arc(x, y, 4, 0, Math.PI * 2);
            context.fill();
            context.stroke();
        });
        context.restore();
    }

    function renderTrend(queryTrend, collectionTrend) {
        const width = Math.max(320, canvas.clientWidth || 640);
        const height = 240;
        const ratio = Math.min(2, window.devicePixelRatio || 1);
        canvas.width = width * ratio;
        canvas.height = height * ratio;
        const context = canvas.getContext("2d");
        context.scale(ratio, ratio);
        const pad = {left: 42, right: 20, top: 34, bottom: 42};
        const chartWidth = width - pad.left - pad.right;
        const chartHeight = height - pad.top - pad.bottom;
        const values = [...queryTrend, ...collectionTrend].map((item) => Number(item.value || 0));
        const maximum = Math.max(1, ...values);
        context.font = '11px "Microsoft YaHei"';
        context.fillStyle = "#8fa9c2";
        context.fillText("新增会话", pad.left, 16);
        context.strokeStyle = "#5ba5d9";
        context.beginPath(); context.moveTo(pad.left + 58, 12); context.lineTo(pad.left + 82, 12); context.stroke();
        context.fillText("采集结果", pad.left + 104, 16);
        context.strokeStyle = "#d7a04c";
        context.setLineDash([6, 5]);
        context.beginPath(); context.moveTo(pad.left + 164, 12); context.lineTo(pad.left + 188, 12); context.stroke();
        context.setLineDash([]);
        for (let index = 0; index <= 4; index += 1) {
            const y = pad.top + chartHeight * index / 4;
            context.strokeStyle = "rgba(143,169,194,.18)";
            context.beginPath(); context.moveTo(pad.left, y); context.lineTo(width - pad.right, y); context.stroke();
            context.fillStyle = "#7895ab";
            context.textAlign = "right";
            context.fillText(String(Math.round(maximum * (4 - index) / 4)), pad.left - 8, y + 4);
        }
        const step = chartWidth / Math.max(1, queryTrend.length - 1);
        const points = (series) => series.map((item, index) => [pad.left + step * index, pad.top + chartHeight - chartHeight * Number(item.value || 0) / maximum]);
        drawSeries(context, points(queryTrend), "#5ba5d9", false);
        drawSeries(context, points(collectionTrend), "#d7a04c", true);
        context.textAlign = "center";
        queryTrend.forEach((item, index) => {
            context.fillStyle = "#7895ab";
            context.fillText(String(item.label || "").slice(5), pad.left + step * index, height - 16);
        });
        const body = document.querySelector("[data-trend-table]");
        if (body) {
            body.replaceChildren();
            queryTrend.forEach((item, index) => {
                const row = document.createElement("tr");
                [item.label, item.value, collectionTrend[index]?.value || 0].forEach((value) => {
                    const cell = document.createElement("td");
                    cell.textContent = value;
                    row.append(cell);
                });
                body.append(row);
            });
        }
    }

    async function refresh() {
        try {
            const data = await app.request("/api/admin/dashboard");
            const dashboard = data.dashboard;
            Object.entries(dashboard.metrics || {}).forEach(([key, value]) => {
                const node = document.querySelector(`[data-metric="${key}"]`);
                if (node) node.textContent = key.endsWith("rate") ? `${value}%` : Number(value).toLocaleString("zh-CN");
            });
            document.querySelector("[data-dashboard-time]").textContent = String(dashboard.refreshed_at || "").slice(11, 19);
            renderTrend(dashboard.query_trend || [], dashboard.collection_trend || []);
            schedule(Number(dashboard.refresh_interval || 30));
        } catch (error) {
            app.announce(app.errorMessage(error, "控制台统计刷新失败"), "error");
        }
    }

    let refreshTimer;
    function schedule(seconds) {
        window.clearInterval(refreshTimer);
        refreshTimer = window.setInterval(refresh, Math.max(5, Math.min(3600, seconds)) * 1000);
    }

    let resizeTimer;
    window.addEventListener("resize", () => {
        window.clearTimeout(resizeTimer);
        resizeTimer = window.setTimeout(refresh, 150);
    });
    refresh();
})();
