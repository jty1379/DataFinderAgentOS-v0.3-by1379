"""将用户会话导出为支持中文、分页、表格与图表的 PDF。"""

from __future__ import annotations

import base64
import io
import json
import os
import re
from datetime import datetime
from html import escape
from pathlib import Path

from reportlab.graphics.charts.piecharts import Pie
from reportlab.graphics.shapes import Circle, Drawing, Line, Rect, String
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Image,
    LongTable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

FONT_NAME = "DataFinderCN"
PAGE_WIDTH, PAGE_HEIGHT = A4
BLUE = colors.HexColor("#246B9E")
NAVY = colors.HexColor("#173B55")
MUTED = colors.HexColor("#637C8D")
LINE = colors.HexColor("#D7E1E8")
PALE = colors.HexColor("#F3F6F9")
AMBER = colors.HexColor("#B65E00")


class PdfExportError(RuntimeError):
    """PDF 构建失败。"""


def _register_font() -> None:
    if FONT_NAME in pdfmetrics.getRegisteredFontNames():
        return
    configured = os.environ.get("DATAFINDER_PDF_FONT", "").strip()
    candidates = [
        configured,
        str(Path(__file__).parents[1] / "static" / "fonts" / "NotoSansSC-Regular.ttf"),
        r"C:\Windows\Fonts\msyh.ttc",
        r"C:\Windows\Fonts\simhei.ttf",
        r"C:\Windows\Fonts\simsun.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            try:
                pdfmetrics.registerFont(TTFont(FONT_NAME, candidate))
                return
            except Exception:
                continue
    # 最后兜底保留 CID 字体，部署文档会提示通过环境变量指定中文字体。
    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    globals()["FONT_NAME"] = "STSong-Light"


def _plain_markdown(value: str) -> str:
    text = re.sub(r"```[^\n]*\n(.*?)```", r"\1", str(value or ""), flags=re.S)
    text = re.sub(r"!\[([^]]*)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"\[([^]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"(^|\s)[#>*_`~-]+", r"\1", text)
    return text.strip()


def _paragraph(value: str, style: ParagraphStyle) -> Paragraph:
    safe = escape(_plain_markdown(value)).replace("\n", "<br/>") or "暂无内容"
    return Paragraph(safe, style)


def _card_payload(message: dict) -> dict:
    metadata = message.get("metadata") or {}
    payload = metadata.get("data")
    if isinstance(payload, dict):
        return payload
    try:
        decoded = json.loads(message.get("content") or "{}")
        return decoded if isinstance(decoded, dict) else {}
    except (TypeError, json.JSONDecodeError):
        return {}


def _inline_image(source: str):
    """仅嵌入消息自带的小型 data URL，绝不由服务端抓取外部地址。"""
    match = re.fullmatch(r"data:image/(png|jpeg);base64,([A-Za-z0-9+/=]+)", str(source or ""))
    if not match or len(match.group(2)) > 4_000_000:
        return None
    try:
        raw = base64.b64decode(match.group(2), validate=True)
        if len(raw) > 3_000_000:
            return None
        image = Image(io.BytesIO(raw))
        image._restrictSize(155 * mm, 92 * mm)
        return image
    except Exception:
        return None


def _chart(title: str, items: list[dict], chart_type: str) -> Drawing:
    width, height = 455, 185
    drawing = Drawing(width, height)
    drawing.add(String(0, height - 16, title[:42] or "数据图表", fontName=FONT_NAME, fontSize=10, fillColor=NAVY))
    values = [max(0.0, float(item.get("value") or 0)) for item in items[:12]]
    labels = [str(item.get("label") or item.get("name") or index + 1)[:8] for index, item in enumerate(items[:12])]
    if not values:
        drawing.add(String(0, 80, "暂无图表数据", fontName=FONT_NAME, fontSize=10, fillColor=MUTED))
        return drawing
    if chart_type in {"pie", "pie_chart", "donut"}:
        total = sum(values) or 1
        palette = [BLUE, colors.HexColor("#4D8EB8"), AMBER, colors.HexColor("#2F7D5D"), colors.HexColor("#7457A8")]
        center_x, center_y, radius = 98, 78, 54
        pie = Pie()
        pie.x = center_x - radius
        pie.y = center_y - radius
        pie.width = radius * 2
        pie.height = radius * 2
        pie.data = values
        pie.labels = None
        pie.startAngle = 90
        for index, (label, value) in enumerate(zip(labels, values, strict=False)):
            y = 142 - index * 18
            color = palette[index % len(palette)]
            pie.slices[index].fillColor = color
            pie.slices[index].strokeColor = colors.white
            drawing.add(Rect(205, y - 7, 9, 9, fillColor=color, strokeColor=None))
            drawing.add(String(220, y - 6, f"{label}  {value:g} ({value / total:.1%})", fontName=FONT_NAME, fontSize=8, fillColor=NAVY))
        drawing.add(pie)
        drawing.add(String(center_x - 18, 8, f"合计 {total:g}", fontName=FONT_NAME, fontSize=8, fillColor=NAVY))
        return drawing
    left, bottom, chart_width, chart_height = 34, 34, 405, 118
    maximum = max(values) or 1
    for step in range(5):
        y = bottom + chart_height * step / 4
        drawing.add(Line(left, y, left + chart_width, y, strokeColor=LINE, strokeWidth=0.5))
    if chart_type in {"bar", "bar_chart"}:
        slot = chart_width / len(values)
        bar_width = min(28, slot * 0.58)
        for index, (label, value) in enumerate(zip(labels, values, strict=False)):
            x = left + index * slot + (slot - bar_width) / 2
            bar_height = chart_height * value / maximum
            drawing.add(Rect(x, bottom, bar_width, bar_height, fillColor=BLUE, strokeColor=None))
            drawing.add(String(x, 17, label, fontName=FONT_NAME, fontSize=6.5, fillColor=MUTED))
            drawing.add(String(x, bottom + bar_height + 3, f"{value:g}", fontName=FONT_NAME, fontSize=6.5, fillColor=NAVY))
    else:
        step = chart_width / max(1, len(values) - 1)
        points: list[tuple[float, float]] = []
        for index, value in enumerate(values):
            points.append((left + index * step, bottom + chart_height * value / maximum))
        for start, end in zip(points, points[1:], strict=False):
            drawing.add(Line(*start, *end, strokeColor=BLUE, strokeWidth=2))
        for (x, y), label, value in zip(points, labels, values, strict=False):
            drawing.add(Circle(x, y, 3, fillColor=colors.white, strokeColor=BLUE, strokeWidth=1.5))
            drawing.add(String(max(0, x - 14), 17, label, fontName=FONT_NAME, fontSize=6.5, fillColor=MUTED))
            drawing.add(String(max(0, x - 7), y + 5, f"{value:g}", fontName=FONT_NAME, fontSize=6.5, fillColor=NAVY))
    return drawing


def _table_flowable(columns: list, rows: list, styles: dict) -> LongTable:
    normalized_columns = []
    for column in columns[:8]:
        if isinstance(column, dict):
            normalized_columns.append((str(column.get("key") or column.get("label") or ""), str(column.get("label") or column.get("key") or "列")))
        else:
            normalized_columns.append((str(column), str(column)))
    if not normalized_columns and rows and isinstance(rows[0], dict):
        normalized_columns = [(str(key), str(key)) for key in list(rows[0])[:8]]
    data = [[Paragraph(escape(label), styles["table_head"]) for _, label in normalized_columns]]
    for row in rows[:200]:
        data.append([Paragraph(escape(str(row.get(key, "--") if isinstance(row, dict) else "--")), styles["table_cell"]) for key, _ in normalized_columns])
    table = LongTable(data or [[Paragraph("暂无表格数据", styles["table_cell"])]], repeatRows=1, hAlign="LEFT")
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E4F0F8")),
        ("TEXTCOLOR", (0, 0), (-1, 0), NAVY),
        ("GRID", (0, 0), (-1, -1), 0.45, LINE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    return table


def _card_story(message: dict, styles: dict) -> list:
    payload = _card_payload(message)
    card_type = payload.get("type") or payload.get("kind") or "text"
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    story: list = []
    if card_type == "weather":
        summary = f"{data.get('location', '天气查询')}：{data.get('summary', '暂无描述')}，{data.get('temperature_c', '--')}°C，湿度 {data.get('humidity', '--')}%。"
        story.append(_paragraph(summary, styles["body"]))
    elif card_type == "analysis":
        story.append(_paragraph(data.get("narrative") or data.get("title") or "问数分析", styles["body"]))
        for view in data.get("visualizations") or []:
            view_type = view.get("type") or "table"
            if view_type == "table":
                columns = [{"key": key, "label": label} for key, label in zip(view.get("columns") or [], view.get("labels") or view.get("columns") or [], strict=False)]
                story.extend([Spacer(1, 4), _paragraph(view.get("title") or "数据表", styles["subhead"]), _table_flowable(columns, view.get("data") or [], styles)])
            elif view_type in {"bar", "line", "donut", "pie"}:
                story.extend([Spacer(1, 4), _chart(view.get("title") or "数据图表", view.get("data") or [], view_type)])
    elif card_type == "table":
        story.append(_table_flowable(data.get("columns") or [], data.get("items") or data.get("rows") or [], styles))
    elif card_type in {"line_chart", "bar_chart", "pie_chart"}:
        story.append(_chart(data.get("title") or "数据图表", data.get("items") or data.get("data") or [], card_type))
    elif card_type in {"image", "video", "music", "news"}:
        title = data.get("title") or {"image": "图片结果", "video": "视频结果", "music": "音频结果", "news": "新闻结果"}.get(card_type, "结果")
        story.append(_paragraph(title, styles["subhead"]))
        if data.get("description"):
            story.append(_paragraph(data["description"], styles["body"]))
        source = data.get("url") or data.get("src")
        if source:
            image = _inline_image(source) if card_type == "image" else None
            if image:
                story.append(image)
            else:
                story.append(_paragraph(f"资源地址：{source}", styles["meta"]))
    else:
        story.append(_paragraph(data.get("text") or data.get("content") or message.get("content") or "暂无内容", styles["body"]))
    return story


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("TitleCN", parent=base["Title"], fontName=FONT_NAME, fontSize=22, leading=30, textColor=NAVY, spaceAfter=6),
        "subtitle": ParagraphStyle("SubtitleCN", parent=base["Normal"], fontName=FONT_NAME, fontSize=10, leading=16, textColor=MUTED),
        "role": ParagraphStyle("RoleCN", parent=base["Heading3"], fontName=FONT_NAME, fontSize=11, leading=16, textColor=BLUE, spaceAfter=4),
        "body": ParagraphStyle("BodyCN", parent=base["BodyText"], fontName=FONT_NAME, fontSize=10.5, leading=18, textColor=colors.HexColor("#233A49"), wordWrap="CJK"),
        "subhead": ParagraphStyle("SubheadCN", parent=base["Heading4"], fontName=FONT_NAME, fontSize=10.5, leading=16, textColor=NAVY),
        "meta": ParagraphStyle("MetaCN", parent=base["BodyText"], fontName=FONT_NAME, fontSize=8, leading=13, textColor=MUTED, wordWrap="CJK"),
        "table_head": ParagraphStyle("TableHeadCN", parent=base["BodyText"], fontName=FONT_NAME, fontSize=8, leading=12, textColor=NAVY, alignment=TA_CENTER, wordWrap="CJK"),
        "table_cell": ParagraphStyle("TableCellCN", parent=base["BodyText"], fontName=FONT_NAME, fontSize=7.5, leading=11, textColor=colors.HexColor("#334B5A"), wordWrap="CJK"),
    }


def build_conversation_pdf(conversation: dict, messages: list[dict], username: str) -> bytes:
    """构建会话 PDF；不联网读取外部媒体，避免导出路径产生 SSRF。"""
    _register_font()
    styles = _styles()
    buffer = io.BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=18 * mm,
        leftMargin=18 * mm,
        topMargin=20 * mm,
        bottomMargin=18 * mm,
        title=conversation.get("title") or "问数会话",
        author="瞭望与问数系统",
    )
    exported_at = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
    story: list = [
        Paragraph("瞭望与问数系统", styles["title"]),
        Paragraph("DataFinder Agent OS · 会话分析报告", styles["subtitle"]),
        Spacer(1, 8),
        Table([
            [Paragraph("用户", styles["meta"]), Paragraph(escape(username), styles["body"])],
            [Paragraph("会话标题", styles["meta"]), Paragraph(escape(conversation.get("title") or "新对话"), styles["body"])],
            [Paragraph("导出时间", styles["meta"]), Paragraph(exported_at, styles["body"])],
            [Paragraph("消息数量", styles["meta"]), Paragraph(str(len(messages)), styles["body"])],
        ], colWidths=[24 * mm, 132 * mm], style=TableStyle([
            ("BACKGROUND", (0, 0), (0, -1), PALE),
            ("GRID", (0, 0), (-1, -1), 0.45, LINE),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 7),
            ("RIGHTPADDING", (0, 0), (-1, -1), 7),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ])),
        Spacer(1, 15),
    ]
    for index, message in enumerate(messages, 1):
        role = "用户" if message.get("role") == "user" else (message.get("metadata") or {}).get("employee") or "智能问数"
        story.append(Paragraph(f"{index:02d} · {escape(str(role))}", styles["role"]))
        if message.get("content_type") == "card":
            story.extend(_card_story(message, styles))
        else:
            story.append(_paragraph(message.get("content") or "", styles["body"]))
        metadata = message.get("metadata") or {}
        source = metadata.get("model") or metadata.get("employee") or ""
        if source or message.get("created_at"):
            story.append(_paragraph(f"{message.get('created_at', '')}  {('· 服务：' + source) if source else ''}", styles["meta"]))
        if index < len(messages):
            story.extend([
                Spacer(1, 7),
                Table(
                    [[""]],
                    colWidths=[159 * mm],
                    rowHeights=[0.4],
                    style=TableStyle([("BACKGROUND", (0, 0), (-1, -1), LINE)]),
                ),
                Spacer(1, 9),
            ])
    if not messages:
        story.append(_paragraph("该会话暂无消息。", styles["body"]))

    def draw_page(canvas, _document):
        canvas.saveState()
        canvas.setStrokeColor(LINE)
        canvas.line(18 * mm, 13 * mm, PAGE_WIDTH - 18 * mm, 13 * mm)
        canvas.setFont(FONT_NAME, 8)
        canvas.setFillColor(MUTED)
        canvas.drawString(18 * mm, 8.5 * mm, "瞭望与问数系统 · 会话导出")
        canvas.drawRightString(PAGE_WIDTH - 18 * mm, 8.5 * mm, f"第 {canvas.getPageNumber()} 页")
        canvas.restoreState()

    try:
        document.build(story, onFirstPage=draw_page, onLaterPages=draw_page)
    except Exception as exc:  # ReportLab 内部异常统一转为可展示导出错误
        raise PdfExportError("PDF 生成失败，请检查会话中的表格或图表数据") from exc
    return buffer.getvalue()
