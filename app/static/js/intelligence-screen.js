(function () {
    "use strict";

    const root = document.querySelector("[data-intelligence-screen]");
    const app = window.DataFinderApp;
    const echarts = window.echarts;
    if (!root || !app || !echarts) return;

    const colors = {blue: "#5ba5d9", amber: "#d7a04c", green: "#55d6a3", purple: "#9b84d7", text: "#8fa9c2", grid: "rgba(143,169,194,.16)"};
    const charts = new Map();
    let timer = null;
    let paused = false;
    let regionalNews = [];

    function chart(name) {
        if (charts.has(name)) return charts.get(name);
        const element = root.querySelector(`[data-chart="${name}"]`);
        const instance = echarts.init(element, null, {renderer: name === "globe" ? "canvas" : "canvas"});
        charts.set(name, instance);
        return instance;
    }

    function axis() {
        return {axisLine: {lineStyle: {color: colors.grid}}, axisLabel: {color: colors.text, fontSize: 10}, splitLine: {lineStyle: {color: colors.grid}}};
    }

    function lineOption(series, labels) {
        return {
            animation: !window.matchMedia("(prefers-reduced-motion: reduce)").matches,
            tooltip: {trigger: "axis"}, legend: {data: series.map((item) => item.name), textStyle: {color: colors.text}, top: 8},
            grid: {left: 42, right: 18, top: 48, bottom: 32},
            xAxis: {...axis(), type: "category", data: labels, boundaryGap: false}, yAxis: {...axis(), type: "value", minInterval: 1},
            series: series.map((item, index) => ({name: item.name, type: "line", data: item.data, smooth: false, symbol: index ? "rect" : "circle", symbolSize: 7, lineStyle: {width: 2, type: index ? "dashed" : "solid"}, itemStyle: {color: item.color}, emphasis: {focus: "series"}}))
        };
    }

    function barOption(items, labelMap = {}) {
        return {
            animation: false, tooltip: {trigger: "axis"}, grid: {left: 70, right: 18, top: 18, bottom: 28},
            xAxis: {...axis(), type: "value", minInterval: 1},
            yAxis: {...axis(), type: "category", data: items.map((item) => labelMap[item.label] || item.label)},
            series: [{type: "bar", data: items.map((item) => item.value), barMaxWidth: 22, itemStyle: {color: colors.blue, borderRadius: [0, 3, 3, 0]}, label: {show: true, position: "right", color: "#dceaf5"}}]
        };
    }

    const worldLand = [
        [[-168,72],[-140,69],[-125,55],[-130,48],[-123,38],[-112,30],[-98,18],[-82,8],[-72,20],[-60,46],[-78,55],[-95,62],[-115,70]],
        [[-82,12],[-72,7],[-66,-5],[-55,-18],[-50,-32],[-61,-54],[-72,-43],[-78,-18]],
        [[-52,83],[-20,80],[-18,65],[-42,59],[-58,68]],
        [[-10,36],[2,48],[20,56],[42,58],[60,70],[98,76],[140,62],[178,67],[160,50],[135,43],[122,30],[110,20],[100,8],[76,8],[61,25],[43,35],[30,31],[15,36]],
        [[-18,35],[2,37],[18,31],[35,15],[51,11],[42,-12],[32,-34],[18,-35],[5,-25],[-8,2]],
        [[112,-11],[129,-13],[145,-20],[154,-39],[138,-44],[118,-32]],
        [[48,-13],[51,-26],[44,-25]],
        [[-180,-63],[-120,-72],[-60,-68],[0,-75],[60,-68],[120,-72],[180,-63],[180,-90],[-180,-90]]
    ];

    const svgNamespace = "http://www.w3.org/2000/svg";

    function svgElement(name, attributes = {}) {
        const element = document.createElementNS(svgNamespace, name);
        Object.entries(attributes).forEach(([key, value]) => element.setAttribute(key, String(value)));
        return element;
    }

    function earthProjection([longitude, latitude]) {
        const radius = 188;
        const centerLongitude = 100 * Math.PI / 180;
        const centerLatitude = 20 * Math.PI / 180;
        const lambda = longitude * Math.PI / 180 - centerLongitude;
        const phi = latitude * Math.PI / 180;
        const visible = Math.sin(centerLatitude) * Math.sin(phi) + Math.cos(centerLatitude) * Math.cos(phi) * Math.cos(lambda);
        return {
            x: 360 + radius * Math.cos(phi) * Math.sin(lambda),
            y: 210 - radius * (Math.cos(centerLatitude) * Math.sin(phi) - Math.sin(centerLatitude) * Math.cos(phi) * Math.cos(lambda)),
            visible: visible >= -0.04
        };
    }

    function earthPath(polygon) {
        const visiblePoints = polygon.map(earthProjection).filter((point) => point.visible);
        if (visiblePoints.length < 3) return "";
        return `${visiblePoints.map((point, index) => `${index ? "L" : "M"}${point.x.toFixed(1)},${point.y.toFixed(1)}`).join(" ")} Z`;
    }

    function renderEarth(points = []) {
        const host = root.querySelector('[data-chart="globe"]');
        const previousChart = charts.get("globe");
        if (previousChart) {
            previousChart.dispose();
            charts.delete("globe");
        }
        host.replaceChildren();

        const svg = svgElement("svg", {
            viewBox: "0 0 720 420",
            role: "img",
            "aria-labelledby": "regional-earth-title regional-earth-description",
            preserveAspectRatio: "xMidYMid meet"
        });
        svg.classList.add("regional-earth");

        const title = svgElement("title", {id: "regional-earth-title"});
        title.textContent = "地区新闻地球分布";
        const description = svgElement("desc", {id: "regional-earth-description"});
        description.textContent = points.length ? "亚洲视角的地球，点击地区新闻数据点可联动右侧新闻列表。" : "亚洲视角的地球，当前没有可定位的地区新闻。";
        svg.append(title, description);

        const defs = svgElement("defs");
        defs.innerHTML = '<radialGradient id="earth-ocean" cx="36%" cy="30%" r="72%"><stop offset="0" stop-color="#174c70"/><stop offset="0.6" stop-color="#0b3351"/><stop offset="1" stop-color="#061d31"/></radialGradient><linearGradient id="earth-land" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#4b91a3"/><stop offset="1" stop-color="#235f75"/></linearGradient><radialGradient id="earth-shade" cx="35%" cy="30%" r="70%"><stop offset="0.55" stop-color="#000" stop-opacity="0"/><stop offset="1" stop-color="#00121f" stop-opacity="0.64"/></radialGradient><filter id="earth-glow" x="-40%" y="-40%" width="180%" height="180%"><feGaussianBlur stdDeviation="4"/></filter><clipPath id="earth-clip"><circle cx="360" cy="210" r="188"/></clipPath>';
        svg.append(defs);

        svg.append(svgElement("circle", {class: "earth-halo", cx: 360, cy: 210, r: 194}));
        svg.append(svgElement("circle", {class: "earth-ocean", cx: 360, cy: 210, r: 188, fill: "url(#earth-ocean)"}));

        const clipped = svgElement("g", {"clip-path": "url(#earth-clip)"});
        const grid = svgElement("g", {class: "earth-grid", "aria-hidden": "true"});
        [-118, -70, 0, 70, 118].forEach((offset) => grid.append(svgElement("ellipse", {cx: 360, cy: 210, rx: Math.max(18, 188 - Math.abs(offset)), ry: 188, transform: `rotate(${offset / 8} 360 210)`})));
        [-116, -60, 0, 60, 116].forEach((offset) => grid.append(svgElement("ellipse", {cx: 360, cy: 210 + offset, rx: Math.sqrt(Math.max(0, 188 * 188 - offset * offset)), ry: Math.max(8, 28 - Math.abs(offset) / 7)})));
        clipped.append(grid);

        const land = svgElement("g", {class: "earth-land"});
        worldLand.forEach((polygon) => {
            const path = earthPath(polygon);
            if (path) land.append(svgElement("path", {d: path, fill: "url(#earth-land)"}));
        });
        clipped.append(land);
        clipped.append(svgElement("circle", {class: "earth-shade", cx: 360, cy: 210, r: 188, fill: "url(#earth-shade)"}));
        svg.append(clipped);
        svg.append(svgElement("circle", {class: "earth-outline", cx: 360, cy: 210, r: 188}));

        const pointLayer = svgElement("g", {class: "earth-points"});
        points.forEach((point) => {
            const projected = earthProjection(point.value || [0, 0]);
            if (!projected.visible) return;
            const count = Number(point.value?.[2] || 0);
            const marker = svgElement("g", {
                class: "earth-marker",
                role: "button",
                tabindex: "0",
                "aria-label": `${point.name}，${count} 条地区新闻`,
                transform: `translate(${projected.x.toFixed(1)} ${projected.y.toFixed(1)})`
            });
            marker.append(svgElement("circle", {class: "earth-marker-hit", r: 22}));
            marker.append(svgElement("circle", {class: "earth-marker-pulse", r: 12, "aria-hidden": "true"}));
            marker.append(svgElement("circle", {class: "earth-marker-dot", r: 5, "aria-hidden": "true"}));
            const label = svgElement("text", {x: 11, y: 4});
            label.textContent = `${point.name} ${count}`;
            marker.append(label);
            const activate = () => showRegionNews(point.name);
            marker.addEventListener("click", activate);
            marker.addEventListener("keydown", (event) => {
                if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    activate();
                }
            });
            pointLayer.append(marker);
        });
        svg.append(pointLayer);

        const legend = svgElement("g", {class: "earth-legend", "aria-hidden": "true"});
        legend.append(svgElement("circle", {cx: 538, cy: 382, r: 4}));
        const legendText = svgElement("text", {x: 550, y: 386});
        legendText.textContent = "地区新闻数据点";
        legend.append(legendText);
        svg.append(legend);
        host.append(svg);
    }

    function renderTable(name, rows) {
        const body = root.querySelector(`[data-table="${name}"]`);
        if (!body) return;
        body.replaceChildren();
        rows.forEach((values) => {
            const row = document.createElement("tr");
            values.forEach((value) => { const cell = document.createElement("td"); cell.textContent = value; row.append(cell); });
            body.append(row);
        });
    }

    function safeNewsUrl(value) {
        try {
            const url = new URL(String(value || ""), window.location.origin);
            return ["http:", "https:"].includes(url.protocol) ? url.href : "";
        } catch (_) { return ""; }
    }

    function showRegionNews(regionName) {
        const region = regionalNews.find((item) => item.name === regionName) || regionalNews[0];
        const list = root.querySelector("[data-region-news]");
        const heading = root.querySelector("[data-region-title]");
        list.replaceChildren();
        root.querySelectorAll("[data-region-button]").forEach((button) => {
            button.setAttribute("aria-pressed", String(Boolean(region && button.dataset.regionButton === region.name)));
        });
        if (!region) {
            heading.textContent = "地区新闻";
            const empty = document.createElement("p");
            empty.textContent = "当前仓库没有可定位的地区新闻。";
            list.append(empty);
            return;
        }
        heading.textContent = `${region.name}新闻 · ${region.count}`;
        (region.articles || []).forEach((article) => {
            const item = document.createElement("article");
            const link = document.createElement("a");
            const url = safeNewsUrl(article.url);
            link.textContent = article.title || "未命名新闻";
            link.href = url || "#";
            if (url) { link.target = "_blank"; link.rel = "noopener noreferrer"; }
            else link.setAttribute("aria-disabled", "true");
            const meta = document.createElement("small");
            meta.textContent = `${article.source || "未标注来源"}${article.published_at ? ` · ${String(article.published_at).slice(0, 16)}` : ""}`;
            item.append(link, meta);
            list.append(item);
        });
    }

    function renderRegionalNews(items) {
        regionalNews = Array.isArray(items) ? items : [];
        const tabs = root.querySelector("[data-region-tabs]");
        tabs.replaceChildren();
        regionalNews.forEach((region) => {
            const button = document.createElement("button");
            button.type = "button";
            button.dataset.regionButton = region.name;
            button.textContent = `${region.name} ${region.count}`;
            button.addEventListener("click", () => showRegionNews(region.name));
            tabs.append(button);
        });
        showRegionNews(regionalNews[0]?.name || "");
    }

    function render(data) {
        const metricLabels = {user_count:"可用用户",today_conversations:"今日对话",model_calls:"模型调用",today_collection:"今日采集",collection_success_rate:"采集成功率",high_risk_alerts:"高风险预警",employee_count:"数字员工"};
        const metricSources = {user_count:"用户表",today_conversations:"会话表",model_calls:"调用日志",today_collection:"采集结果",collection_success_rate:"采集任务",high_risk_alerts:"预警库",employee_count:"员工配置"};
        const kpis = root.querySelector("[data-intelligence-kpis]");
        kpis.replaceChildren();
        Object.entries(metricLabels).forEach(([key, label]) => {
            const item = document.createElement("article"); item.className = `screen-kpi${key === "high_risk_alerts" ? " alert" : ""}`;
            const span = document.createElement("span"); span.textContent = label;
            const strong = document.createElement("strong"); strong.textContent = `${Number(data.metrics[key] || 0).toLocaleString("zh-CN")}${key.endsWith("rate") ? "%" : ""}`;
            const small = document.createElement("small"); small.textContent = `来源：${metricSources[key]}`;
            item.append(span,strong,small); kpis.append(item);
        });

        const points = data.geo_points || [];
        renderRegionalNews(data.regional_news || []);
        root.querySelector('[data-empty="globe"]').hidden = points.length > 0;
        renderEarth(points);
        chart("source").setOption(barOption(data.source_distribution || []), true);
        renderTable("source", (data.source_distribution || []).map((item)=>[item.label,item.value]));
        chart("collection").setOption(lineOption([{name:"采集结果",data:(data.collection_trend||[]).map((item)=>item.value),color:colors.blue}],(data.collection_trend||[]).map((item)=>item.label.slice(5))),true);
        renderTable("collection", (data.collection_trend || []).map((item)=>[item.label,item.value]));
        chart("activity").setOption(lineOption([{name:"模型调用",data:(data.model_trend||[]).map((item)=>item.value),color:colors.amber},{name:"用户消息",data:(data.user_activity||[]).map((item)=>item.value),color:colors.green}],(data.model_trend||[]).map((item)=>item.label.slice(5))),true);
        renderTable("activity", (data.model_trend || []).map((item,index)=>[item.label,item.value,data.user_activity?.[index]?.value || 0]));
        chart("risk").setOption(barOption(data.risk_distribution || [],{critical:"重大",high:"高",medium:"中",low:"低"}),true);
        const cloud = root.querySelector("[data-word-cloud]"); cloud.replaceChildren();
        const maxWord = Math.max(1,...(data.word_cloud||[]).map((item)=>item.value));
        (data.word_cloud || []).forEach((item)=>{const node=document.createElement("span");node.textContent=`${item.name} ${item.value}`;node.style.setProperty("--weight",String(Math.round(item.value/maxWord*6)));cloud.append(node);});
        if (!cloud.children.length) { const empty=document.createElement("span");empty.textContent="仓库暂无可统计文本";cloud.append(empty); }
        const hotspots = root.querySelector("[data-hotspots]"); hotspots.replaceChildren();
        (data.hotspots || []).forEach((item,index)=>{const li=document.createElement("li"),rank=document.createElement("em"),box=document.createElement("div"),title=document.createElement("b"),meta=document.createElement("small");rank.textContent=String(index+1).padStart(2,"0");title.textContent=item.title;meta.textContent=`${item.source} · ${String(item.created_at).slice(0,16)}`;box.append(title,meta);li.append(rank,box);hotspots.append(li);});
        if (!hotspots.children.length) { const li=document.createElement("li");li.textContent="暂无入仓热点";hotspots.append(li); }
        root.querySelector("[data-screen-refreshed]").textContent = `最近刷新 ${String(data.refreshed_at || "").replace("T"," ").slice(0,19)}`;
    }

    async function refresh() {
        root.setAttribute("aria-busy","true");
        try { const response=await app.request("/api/admin/screens/intelligence"); render(response.screen); }
        catch(error){app.announce(app.errorMessage(error,"数智大屏刷新失败"),"error");}
        finally{root.removeAttribute("aria-busy");}
    }
    function schedule(){window.clearInterval(timer);if(!paused)timer=window.setInterval(refresh,60000);}
    root.querySelector("[data-screen-refresh]").addEventListener("click",refresh);
    root.querySelector("[data-screen-pause]").addEventListener("click",(event)=>{paused=!paused;event.currentTarget.setAttribute("aria-pressed",String(paused));event.currentTarget.innerHTML=paused?'<i class="layui-icon layui-icon-play"></i>继续刷新':'<i class="layui-icon layui-icon-pause"></i>暂停刷新';schedule();});
    root.querySelector("[data-screen-fullscreen]").addEventListener("click",()=>document.fullscreenElement?document.exitFullscreen():root.requestFullscreen());
    let resizeTimer;window.addEventListener("resize",()=>{clearTimeout(resizeTimer);resizeTimer=setTimeout(()=>charts.forEach((item)=>item.resize()),150);});
    refresh();schedule();
})();
