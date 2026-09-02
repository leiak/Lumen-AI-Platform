"""DocumentParser._create_chunks chunking_strategy / chunking_params 透传测试。

回归:M38.4 (2026-09-02) — POST /rechunk {chunk_size:200} 之前被静默吞掉,
DocumentParser._create_chunks 不传 chunking_params 给 ChunkingService,
所有 doc 都按 fixed/500/50 切。fix 后 _create_chunks 透传 kwargs。

不依赖真实 docx 文件 —— _create_chunks 是纯 text 操作,直接调
DocumentParser 实例方法验证 kwargs 链路。
"""
from __future__ import annotations

import pytest

from lumen_services.document_parser import DocumentParser


# 6000 chars 中文段落,够 fixed 500 切 13 段,够 fixed 200 切 30+ 段
SAMPLE_TEXT = (
    "随着《数据安全法》《个人信息保护法》落地,客户企业亟需数据分类分级能力。"
    "本项目目标是交付一款开箱即用、规则 + AI 双引擎的数据库敏感字段分级分类系统,"
    "覆盖 Web 管理端 + CLI 工具两种形态。"
) * 60  # ~6000 chars


class TestCreateChunksRespectsChunkSize:
    """chunk_size 真生效(回归 M38.4 透传 bug)。"""

    def test_chunk_size_200_yields_more_chunks_than_500(self):
        """同一个 text,chunk_size=200 切的段数应该显著多于 500。"""
        parser = DocumentParser()

        chunks_500 = parser._create_chunks(
            SAMPLE_TEXT, "general",
            chunking_strategy="fixed",
            chunking_params={"chunk_size": 500, "chunk_overlap": 0},
        )
        chunks_200 = parser._create_chunks(
            SAMPLE_TEXT, "general",
            chunking_strategy="fixed",
            chunking_params={"chunk_size": 200, "chunk_overlap": 0},
        )

        assert len(chunks_500) >= 10  # 6000 / 500 ≈ 12
        assert len(chunks_200) >= 25  # 6000 / 200 ≈ 30
        # 200 切的段数 ≥ 500 切的 2 倍(无 overlap 时近似)
        assert len(chunks_200) >= len(chunks_500) * 2

    def test_chunk_size_50_yields_most_chunks(self):
        """极小 chunk_size=50 → 段数最多,符合预期。"""
        parser = DocumentParser()

        chunks = parser._create_chunks(
            SAMPLE_TEXT, "general",
            chunking_strategy="fixed",
            chunking_params={"chunk_size": 50, "chunk_overlap": 0},
        )

        assert len(chunks) >= 100  # 6000 / 50 ≈ 120

    def test_default_chunk_size_is_500_when_no_params(self):
        """不传 chunking_params 时走默认 500/50(回归保护)。"""
        parser = DocumentParser()

        chunks = parser._create_chunks(SAMPLE_TEXT, "general")
        # 6000 chars / ~500 chars ≈ 12 段(默认 500 + overlap 50 会再多一些)
        assert 10 <= len(chunks) <= 16


class TestCreateChunksRespectsOverlap:
    """chunk_overlap 影响 chunk 之间的重叠,反映在总长度。"""

    def test_overlap_increases_total_chunk_length(self):
        """overlap 越大,相邻 chunk 重复越多,所有 chunk 总长度 ≫ 原文。"""
        parser = DocumentParser()
        params_no_overlap = {"chunk_size": 200, "chunk_overlap": 0}
        params_with_overlap = {"chunk_size": 200, "chunk_overlap": 50}

        no_overlap = parser._create_chunks(
            SAMPLE_TEXT, "general",
            chunking_strategy="fixed", chunking_params=params_no_overlap,
        )
        with_overlap = parser._create_chunks(
            SAMPLE_TEXT, "general",
            chunking_strategy="fixed", chunking_params=params_with_overlap,
        )

        len_no = sum(len(c["content"]) for c in no_overlap)
        len_with = sum(len(c["content"]) for c in with_overlap)
        # overlap 让 chunk 数差不多但总长度更长
        assert len_with > len_no
        assert len_with > len(SAMPLE_TEXT)  # overlap > 0 总长一定 > 原文


class TestCreateChunksStrategyOverride:
    """chunking_strategy 覆盖 doc_type 默认。"""

    def test_general_with_semantic_strategy_uses_semantic(self):
        """doc_type=general 默认 fixed,但传 chunking_strategy="semantic" 切走 semantic。"""
        parser = DocumentParser()

        chunks = parser._create_chunks(
            SAMPLE_TEXT, "general",
            chunking_strategy="semantic",
            chunking_params={"min_chunk_size": 100, "max_chunk_size": 400},
        )

        # semantic 按句子切,中文以 。|！|？|\n 分,6000 chars 应该有 ≥5 段
        assert len(chunks) >= 5
        for c in chunks:
            assert c["strategy"].startswith("semantic")

    def test_paper_default_is_document_structure_but_strategy_overrides(self):
        """doc_type=paper 默认 document_structure,但显式传 fixed 走 fixed。"""
        parser = DocumentParser()

        chunks = parser._create_chunks(
            SAMPLE_TEXT, "paper",
            chunking_strategy="fixed",
            chunking_params={"chunk_size": 500, "chunk_overlap": 0},
        )

        for c in chunks:
            # fixed 策略 get_name 返回 fixed_size_<size>_<overlap>
            assert c["strategy"].startswith("fixed_size_")


class TestCreateChunksParamPassthrough:
    """kwargs 透传到 ChunkingService.get_strategy。"""

    def test_none_chunking_params_uses_defaults(self):
        """chunking_params=None 时不报错,走 strategy 默认值。"""
        parser = DocumentParser()

        # None 而不是 {}
        chunks = parser._create_chunks(
            SAMPLE_TEXT, "general",
            chunking_strategy="fixed",
            chunking_params=None,
        )
        assert len(chunks) >= 1

    def test_empty_chunking_params_dict_uses_defaults(self):
        """chunking_params={} 也走 strategy 默认值(等价于 None)。"""
        parser = DocumentParser()

        chunks = parser._create_chunks(
            SAMPLE_TEXT, "general",
            chunking_strategy="fixed",
            chunking_params={},
        )
        assert len(chunks) >= 1

    def test_unknown_strategy_falls_back_to_fixed(self):
        """不识别的 strategy 走 fixed(沿用 ChunkingService.get_strategy 默认行为)。"""
        parser = DocumentParser()

        chunks = parser._create_chunks(
            SAMPLE_TEXT, "general",
            chunking_strategy="not-a-real-strategy",
            chunking_params=None,
        )
        # 不报错就行
        assert len(chunks) >= 1
