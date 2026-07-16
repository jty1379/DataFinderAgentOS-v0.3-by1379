(function () {
    "use strict";

    const qs = (selector, root = document) => root.querySelector(selector);
    const qsa = (selector, root = document) => Array.from(root.querySelectorAll(selector));

    function showNotice(message) {
        window.DataFinderApp?.announce(message, "info", {duration: 2000});
    }

    qsa("[data-password-toggle]").forEach((button) => {
        button.addEventListener("click", () => {
            const input = document.getElementById(button.dataset.passwordToggle);
            if (!input) return;
            const visible = input.type === "text";
            input.type = visible ? "password" : "text";
            button.setAttribute("aria-label", visible ? "显示密码" : "隐藏密码");
        });
    });

    qsa("form[data-submit-lock]").forEach((form) => {
        form.addEventListener("submit", () => {
            const button = qs("button[type='submit']", form);
            if (!button) return;
            button.disabled = true;
            const label = qs("span", button);
            if (label) label.textContent = "正在验证…";
        });
    });

    qsa("[data-demo-notice]").forEach((button) => {
        button.addEventListener("click", (event) => {
            if (button.tagName === "A") event.preventDefault();
            showNotice(button.dataset.demoNotice);
        });
    });

    const clock = qs("[data-live-clock]");
    if (clock) {
        const updateClock = () => {
            const now = new Date();
            clock.textContent = now.toLocaleTimeString("zh-CN", {hour12: false});
            const date = qs("[data-current-date]");
            if (date) date.textContent = now.toLocaleDateString("zh-CN", {year: "numeric", month: "long", day: "numeric", weekday: "long"});
            const greeting = qs("[data-greeting]");
            if (greeting) {
                const hour = now.getHours();
                greeting.textContent = hour < 6 ? "夜深了" : hour < 11 ? "早上好" : hour < 14 ? "中午好" : hour < 18 ? "下午好" : "晚上好";
            }
        };
        updateClock();
        window.setInterval(updateClock, 1000);
    }

    const sidebar = qs("[data-admin-sidebar]");
    if (sidebar) {
        const backdrop = qs("[data-sidebar-backdrop]");
        const toggle = qs("[data-sidebar-toggle]");
        const closeSidebar = () => {
            sidebar.classList.remove("open");
            backdrop.classList.remove("show");
        };
        toggle.addEventListener("click", () => {
            sidebar.classList.add("open");
            backdrop.classList.add("show");
        });
        backdrop.addEventListener("click", closeSidebar);
        qsa("[data-admin-link]", sidebar).forEach((link) => link.addEventListener("click", closeSidebar));
    }

    qsa("[data-dialog-open]").forEach((button) => {
        button.addEventListener("click", () => {
            const dialog = document.getElementById(button.dataset.dialogOpen);
            if (dialog && !button.disabled) dialog.showModal();
        });
    });
    qsa("[data-dialog-close]").forEach((button) => {
        button.addEventListener("click", () => button.closest("dialog")?.close());
    });
    qsa("dialog.management-dialog").forEach((dialog) => {
        dialog.addEventListener("click", (event) => {
            if (event.target === dialog) dialog.close();
        });
    });
    qsa("form[data-confirm]").forEach((form) => {
        form.addEventListener("submit", (event) => {
            if (!window.confirm(form.dataset.confirm)) event.preventDefault();
        });
    });

    function drawTrendChart() {
        const canvas = qs("#query-trend-chart");
        if (!canvas) return;
        const rect = canvas.getBoundingClientRect();
        const dpr = Math.min(window.devicePixelRatio || 1, 2);
        canvas.width = Math.max(320, rect.width * dpr);
        canvas.height = 190 * dpr;
        const ctx = canvas.getContext("2d");
        ctx.scale(dpr, dpr);
        const width = canvas.width / dpr;
        const height = 190;
        const values = [12, 19, 16, 25, 23, 31, 42];
        const labels = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"];
        const left = 18, right = 14, top = 18, bottom = 27;
        const chartWidth = width - left - right;
        const chartHeight = height - top - bottom;

        ctx.clearRect(0, 0, width, height);
        ctx.strokeStyle = "rgba(111,174,219,.10)";
        ctx.lineWidth = 1;
        for (let index = 0; index < 4; index += 1) {
            const y = top + chartHeight * index / 3;
            ctx.beginPath(); ctx.moveTo(left, y); ctx.lineTo(width - right, y); ctx.stroke();
        }
        const points = values.map((value, index) => ({
            x: left + chartWidth * index / (values.length - 1),
            y: top + chartHeight * (1 - value / 48)
        }));
        ctx.beginPath(); points.forEach((point, index) => index ? ctx.lineTo(point.x, point.y) : ctx.moveTo(point.x, point.y));
        ctx.strokeStyle = "#4b8fca"; ctx.lineWidth = 2; ctx.stroke();
        points.forEach((point) => { ctx.beginPath(); ctx.arc(point.x, point.y, 3, 0, Math.PI * 2); ctx.fillStyle = "#071426"; ctx.fill(); ctx.strokeStyle = "#8bb7d7"; ctx.stroke(); });
        ctx.fillStyle = "#68859a"; ctx.font = "9px Microsoft YaHei"; ctx.textAlign = "center";
        labels.forEach((label, index) => ctx.fillText(label, points[index].x, height - 7));
    }
    drawTrendChart();
    let chartTimer;
    window.addEventListener("resize", () => { window.clearTimeout(chartTimer); chartTimer = window.setTimeout(drawTrendChart, 100); });
})();
