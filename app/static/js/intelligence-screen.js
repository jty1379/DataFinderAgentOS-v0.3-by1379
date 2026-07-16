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

    function globeTexture() {
        const canvas = document.createElement("canvas");
        canvas.width = 1024; canvas.height = 512;
        const context = canvas.getContext("2d");
        context.fillStyle = "#09243a"; context.fillRect(0, 0, canvas.width, canvas.height);
        context.strokeStyle = "rgba(91,165,217,.26)"; context.lineWidth = 1;
        for (let x = 0; x <= canvas.width; x += 64) { context.beginPath(); context.moveTo(x, 0); context.lineTo(x, canvas.height); context.stroke(); }
        for (let y = 0; y <= canvas.height; y += 64) { context.beginPath(); context.moveTo(0, y); context.lineTo(canvas.width, y); context.stroke(); }
        context.fillStyle = "rgba(75,143,202,.16)";
        [[150,130,190,70],[365,170,120,90],[560,90,210,85],[735,165,135,110],[850,300,80,58],[420,330,100,65]].forEach(([x,y,w,h]) => { context.beginPath(); context.ellipse(x,y,w,h,0,0,Math.PI*2); context.fill(); });
        return canvas;
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
        root.querySelector('[data-empty="globe"]').hidden = points.length > 0;
        try {
            chart("globe").setOption({
                backgroundColor:"transparent", tooltip:{formatter:(params)=>`${params.name}<br>内容提及 ${params.value?.[2] || 0} 次`},
                globe:{baseTexture:globeTexture(),shading:"lambert",environment:"#0d2439",light:{main:{intensity:1.1,shadow:false},ambient:{intensity:.35}},viewControl:{autoRotate:points.length > 0 && !window.matchMedia("(prefers-reduced-motion: reduce)").matches,autoRotateSpeed:5,distance:190},globeRadius:70},
                series:[{type:"scatter3D",coordinateSystem:"globe",data:points,symbolSize:(value)=>Math.min(18,7+Number(value[2]||0)),itemStyle:{color:colors.amber,opacity:.95}}]
            }, true);
        } catch (error) {
            root.querySelector('[data-empty="globe"]').hidden = false;
            root.querySelector('[data-empty="globe"]').textContent = "当前设备无法启用 WebGL 3D 地球，其余统计仍可正常查看。";
        }
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
