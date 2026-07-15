"""
单元测试: 分块服务
"""
import pytest
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from lumen_services.chunking_service import (
    ChunkingService,
    FixedSizeChunking,
    SemanticChunking,
    DocumentStructureChunking
)


class TestFixedSizeChunking:
    """固定大小分块测试"""

    def test_basic_split(self):
        """基本分块测试"""
        chunker = FixedSizeChunking(chunk_size=100, chunk_overlap=10)
        text = "A" * 300  # 300字符文本

        chunks = chunker.split(text)
        assert len(chunks) > 1

    def test_small_text(self):
        """小于分块大小的文本"""
        chunker = FixedSizeChunking(chunk_size=500, chunk_overlap=50)
        text = "短文本"

        chunks = chunker.split(text)
        assert len(chunks) == 1
        assert chunks[0] == "短文本"

    def test_overlap(self):
        """重叠测试"""
        chunker = FixedSizeChunking(chunk_size=100, chunk_overlap=20)
        text = "ABCDEFGHIJKLMNOPQRSTUVWXYZ" * 10  # 260 chars, 10 repeats of 26 chars

        chunks = chunker.split(text)
        # 验证重叠存在 - 检查相邻块是否有重复内容区域
        assert len(chunks) > 1
        # 重叠应该导致某些内容在多个块中重复
        total_chunk_len = sum(len(c) for c in chunks)
        assert total_chunk_len > len(text)  # 有重叠时总长度大于原文


class TestSemanticChunking:
    """语义分块测试"""

    def test_sentence_splitting(self):
        """句子分割测试"""
        chunker = SemanticChunking(min_chunk_size=50, max_chunk_size=200)
        text = "这是第一句。这是第二句。这是第三句。"

        chunks = chunker.split(text)
        assert len(chunks) >= 1

    def test_chinese_text(self):
        """中文文本分块"""
        chunker = SemanticChunking(min_chunk_size=20, max_chunk_size=100)
        text = "今天天气很好。我们去公园玩。公园里有很多花。"

        chunks = chunker.split(text)
        assert len(chunks) >= 1
        # 验证中文分句
        assert all("。" in chunk or len(chunk) < 20 for chunk in chunks)

    def test_long_sentence(self):
        """长句子处理"""
        chunker = SemanticChunking(min_chunk_size=50, max_chunk_size=100)
        text = "这是一条非常非常非常非常非常非常长的句子，" * 10 + "后面终于结束了。"

        chunks = chunker.split(text)
        # 长句子应该被分割
        assert len(chunks) > 1

    def test_empty_text(self):
        """空文本处理"""
        chunker = SemanticChunking()
        chunks = chunker.split("")
        assert chunks == []

    def test_preserves_meaning(self):
        """语义完整性测试"""
        chunker = SemanticChunking(min_chunk_size=30, max_chunk_size=200)
        text = "人工智能是计算机科学的一个分支。机器学习是人工智能的子领域。深度学习又是机器学习的子领域。"

        chunks = chunker.split(text)
        # 验证句子没有被分割
        for chunk in chunks:
            # 每个块应该包含完整句子
            assert "人工智能" in chunk or "机器学习" in chunk or "深度学习" in chunk


class TestDocumentStructureChunking:
    """文档结构分块测试"""

    def test_heading_detection(self):
        """标题检测"""
        chunker = DocumentStructureChunking(max_chunk_size=200)
        text = """第一章
这是第一章的内容。

第二章
这是第二章的内容。
"""

        chunks = chunker.split(text)
        assert len(chunks) >= 1

    def test_numbered_list(self):
        """数字列表处理"""
        chunker = DocumentStructureChunking(max_chunk_size=200)
        text = """1. 第一项
2. 第二项
3. 第三项
"""

        chunks = chunker.split(text)
        assert len(chunks) >= 1

    def test_chinese_numbering(self):
        """中文数字列表"""
        chunker = DocumentStructureChunking(max_chunk_size=200)
        text = """一、项目目标
本项目的主要目标。

二、项目计划
本项目的计划内容。
"""

        chunks = chunker.split(text)
        assert len(chunks) >= 1

    def test_is_heading_matches_chinese_parenthesis_format(self):
        """M29.2 (2026-06-15): 验证 ``（一）`` / ``（二）`` 格式中文数字
        二级标题被识别为 heading。精准停车功能文档.docx 大量段以
        ``（一）医院场景`` 开头,原正则不识别,被孤立成 21 字符 chunk。

        验证策略: 用 ``max_chunk_size=80`` 强制让每个 heading 切出
        独立 chunk,验证 ``（一）`` 段和 ``（二）`` 段都被识别。
        """
        chunker = DocumentStructureChunking(max_chunk_size=80)
        text = """项目概述
本项目是关于精准停车的功能描述。
（一）医院场景
医院场景下的预约流程说明,需要用户先在 App 内完成车辆绑定。
（二）商业场景
商业场景下的批量预约支持。
"""
        chunks = chunker.split(text)
        # 期望至少 3 个 chunk: 标题触发 split,2 个 heading 段各开新 chunk
        assert len(chunks) >= 3, f"期望 >=3 chunks,实际 {len(chunks)}: {chunks}"
        # 关键修复: "（一）医院场景" 段标题与正文没脱节
        # (原 bug: "（一）医院场景" 被孤立成 ~7 字符 chunk)
        # "（一）医院场景" 段标题 + "医院场景下..." 正文必须在同一 chunk
        hospital_body_chunk = [
            c for c in chunks
            if "（一）医院场景" in c and "医院场景下的预约流程" in c
        ]
        assert len(hospital_body_chunk) >= 1, (
            f"'（一）医院场景' 与 '医院场景下...' 正文应在同一 chunk,"
            f"实际 chunks: {chunks}"
        )
        # "（二）商业场景" 段标题 + "商业场景下..." 正文也应在同一 chunk
        business_body_chunk = [
            c for c in chunks
            if "（二）商业场景" in c and "商业场景下的批量预约" in c
        ]
        assert len(business_body_chunk) >= 1, (
            f"'（二）商业场景' 与 '商业场景下...' 正文应在同一 chunk,"
            f"实际 chunks: {chunks}"
        )
        # 关键: 没有孤立标题 chunk(单行 heading 被孤立)。
        # 原 bug: "（一）医院场景" 这种单行 heading 段被孤立成
        # ~7-21 字符 chunk,与正文脱节。修法: heading 触发 split 后
        # 必须把 heading 与其后面的正文合到同一 chunk。
        for c in chunks:
            if c.count("\n") == 0:
                # 单行 chunk,检查它是不是一个 heading(单行 heading 也算孤立)
                line = c.strip()
                is_standalone_heading = bool(
                    re.match(r'^[（(][一二三四五六七八九十]+[）)]', line)
                    or re.match(r'^[一二三四五六七八九十]+[）)]', line)
                    or re.match(r'^[（(]\d+[）)]', line)
                )
                assert not is_standalone_heading, (
                    f"发现孤立 heading chunk: '{c[:80]}'"
                )

    def test_is_heading_matches_arabic_parenthesis_format(self):
        """M29.2: 验证 ``（1）`` / ``（2）`` / ``（a）`` 阿拉伯数字
        格式标题被识别为 heading。
        """
        chunker = DocumentStructureChunking(max_chunk_size=80)
        text = """操作流程
请按照以下步骤操作。
（1）打开 App
进入 App 后,在个人中心页面中设有"车辆管理"入口。
（2）添加车辆
点击"添加车辆"按钮,填写车牌信息。
（a）特殊场景
特殊场景说明。
"""
        chunks = chunker.split(text)
        # 验证 ``（1）`` 和 ``（a）`` 都触发 chunk 边界
        assert len(chunks) >= 2, f"期望 >=2 chunks,实际 {len(chunks)}: {chunks}"
        # 关键: "（1）打开 App" 标题与 "个人中心页面" 内容不脱节
        app_chunk = [c for c in chunks if "打开 App" in c]
        assert len(app_chunk) == 1
        assert "个人中心页面" in app_chunk[0], (
            "标题 '（1）打开 App' 与正文 '个人中心页面' 被错误切分"
        )

    def test_split_on_chinese_parenthesis_heading(self):
        """M29.2 端到端: 验证 ``（一）`` 触发 chunk 边界后,长内容不会
        跨越 heading 被错误合并。
        """
        chunker = DocumentStructureChunking(max_chunk_size=100)
        # 构造长正文让 max_chunk_size=100 强制切分
        text = """（一）医院场景预约流程
医院场景下,用户需要先在 App 内完成车辆绑定,然后选择就诊医院,选择就诊时间,确认预约信息后提交即可。
（二）商业场景批量预约
商业场景支持批量预约,可以一次性为多辆车预约停车位。
"""
        chunks = chunker.split(text)
        # 期望 2 个 chunk: 一个含 "（一）医院场景预约流程" 段,另一个含
        # "（二）商业场景批量预约" 段
        assert len(chunks) == 2, f"期望 2 chunks,实际 {len(chunks)}: {chunks}"

        # 验证 ``（一）`` 段含完整描述,``（二）`` 段也含完整描述
        assert "（一）" in chunks[0]
        assert "（二）" in chunks[1]
        # 关键: 没有 21 字符的孤立标题 chunk
        for c in chunks:
            assert len(c) > 30, f"发现孤立短 chunk: '{c}'"


class TestChunkingService:
    """分块服务测试"""

    def test_get_fixed_strategy(self):
        """获取固定分块策略"""
        service = ChunkingService()
        strategy = service.get_strategy("fixed", chunk_size=200)
        assert isinstance(strategy, FixedSizeChunking)

    def test_get_semantic_strategy(self):
        """获取语义分块策略"""
        service = ChunkingService()
        strategy = service.get_strategy("semantic")
        assert isinstance(strategy, SemanticChunking)

    def test_get_document_structure_strategy(self):
        """获取文档结构分块策略"""
        service = ChunkingService()
        strategy = service.get_strategy("document_structure")
        assert isinstance(strategy, DocumentStructureChunking)

    def test_split_with_metadata(self):
        """带元数据的分块"""
        service = ChunkingService()
        result = service.split_with_metadata(
            "第一句。第二句。第三句。",
            strategy_name="semantic"
        )
        assert len(result) >= 1
        assert "content" in result[0]
        assert "chunk_index" in result[0]
        assert "strategy" in result[0]

    def test_get_available_strategies(self):
        """获取可用策略列表"""
        service = ChunkingService()
        strategies = service.get_available_strategies()
        assert len(strategies) == 3
        assert any(s["name"] == "fixed" for s in strategies)
        assert any(s["name"] == "semantic" for s in strategies)
        assert any(s["name"] == "document_structure" for s in strategies)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
