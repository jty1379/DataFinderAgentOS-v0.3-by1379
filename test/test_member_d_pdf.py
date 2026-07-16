"""成员 D 会话 PDF 导出验收。"""

from __future__ import annotations

import io
import unittest

from pypdf import PdfReader

from app.services.pdf_export import build_conversation_pdf


def sample_pdf() -> bytes:
    conversation = {"id": 1, "title": "成都市政务数据七日运行分析"}
    messages = [
        {
            "role": "user",
            "content_type": "text",
            "content": "# 分析任务\n\n请汇总最近七日数据：\n- 采集趋势\n- 风险变化\n- 后续建议",
            "metadata": {},
            "created_at": "2026-07-16 10:00",
        },
        {
            "role": "assistant",
            "content_type": "card",
            "content": "{}",
            "metadata": {
                "employee": "数据分析师",
                "data": {
                    "kind": "analysis",
                    "title": "七日运行分析",
                    "narrative": "本周采集量整体上升，高风险预警集中在周三与周五。",
                    "visualizations": [
                        {
                            "type": "line",
                            "title": "七日采集趋势",
                            "data": [
                                {"label": "周一", "value": 26},
                                {"label": "周二", "value": 31},
                                {"label": "周三", "value": 44},
                                {"label": "周四", "value": 39},
                                {"label": "周五", "value": 58},
                                {"label": "周六", "value": 52},
                                {"label": "周日", "value": 63},
                            ],
                        },
                        {
                            "type": "table",
                            "title": "来源状态",
                            "columns": ["source", "count", "status"],
                            "labels": ["数据来源", "采集量", "状态"],
                            "data": [
                                {"source": "政务公开网", "count": 128, "status": "在线"},
                                {"source": "新闻瞭源", "count": 96, "status": "在线"},
                                {"source": "风险预警库", "count": 18, "status": "需复核"},
                            ],
                        },
                    ],
                },
            },
            "created_at": "2026-07-16 10:01",
        },
        {
            "role": "assistant",
            "content_type": "text",
            "content": "## 处置建议\n\n1. 对高风险来源执行人工复核。\n2. 保留采集任务证据链。\n3. 导出报告后归档。\n\n"
            + "这是一段用于验证长对话自动分页的中文说明。" * 140,
            "metadata": {"model": "课堂演示模型"},
            "created_at": "2026-07-16 10:02",
        },
        {
            "role": "assistant",
            "content_type": "card",
            "content": "{}",
            "metadata": {
                "data": {
                    "type": "image",
                    "data": {
                        "title": "风险分布缩略图",
                        "description": "会话内嵌图片导出验证",
                        "src": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=",
                    },
                }
            },
            "created_at": "2026-07-16 10:03",
        },
    ]
    return build_conversation_pdf(conversation, messages, "齐语林")


class MemberDPdfTest(unittest.TestCase):
    def test_chinese_chart_table_and_long_conversation_export(self):
        content = sample_pdf()
        self.assertTrue(content.startswith(b"%PDF"))
        reader = PdfReader(io.BytesIO(content))
        self.assertGreaterEqual(len(reader.pages), 2)
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
        for expected in ("瞭望与问数系统", "齐语林", "成都市政务数据七日运行分析", "政务公开网", "处置建议"):
            self.assertIn(expected, text)


if __name__ == "__main__":
    unittest.main()
