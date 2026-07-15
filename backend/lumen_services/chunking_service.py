"""
文本分块服务 - 支持多种分块策略
"""
import re
from typing import List, Dict, Any, Optional, Callable
from abc import ABC, abstractmethod
from langchain_text_splitters import RecursiveCharacterTextSplitter, Language


class ChunkingStrategy(ABC):
    """分块策略抽象基类"""

    @abstractmethod
    def split(self, text: str) -> List[str]:
        """分割文本"""
        pass

    @abstractmethod
    def get_name(self) -> str:
        """获取策略名称"""
        pass


class FixedSizeChunking(ChunkingStrategy):
    """固定大小分块 - 传统的重叠窗口分块"""

    def __init__(self, chunk_size: int = 500, chunk_overlap: int = 50):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            length_function=len,
        )

    def split(self, text: str) -> List[str]:
        return self.splitter.split_text(text)

    def get_name(self) -> str:
        return f"fixed_size_{self.chunk_size}_{self.chunk_overlap}"


class SemanticChunking(ChunkingStrategy):
    """
    语义分块 - 基于句子边界的智能分块
    尝试在语义完整的地方切分，确保每个块有独立意义
    """

    def __init__(
        self,
        min_chunk_size: int = 200,
        max_chunk_size: int = 800,
        sentence_separators: List[str] = None
    ):
        self.min_chunk_size = min_chunk_size
        self.max_chunk_size = max_chunk_size
        self.sentence_separators = sentence_separators or [
            '。', '！', '？', '\n', '；', '|', '◆', '■', '●'
        ]

    def split(self, text: str) -> List[str]:
        """语义分块核心逻辑"""
        # 1. 先按句子分割
        sentences = self._split_into_sentences(text)
        if not sentences:
            return [text] if text else []

        # 2. 将句子聚合成块
        chunks = []
        current_chunk = []
        current_length = 0

        for sentence in sentences:
            sentence_len = len(sentence)
            # 如果单个句子超过最大块大小，强制切割
            if sentence_len > self.max_chunk_size:
                # 保存当前块
                if current_chunk:
                    chunks.append(''.join(current_chunk))
                    current_chunk = []
                    current_length = 0

                # 切割长句子
                sub_chunks = self._split_long_sentence(sentence)
                chunks.extend(sub_chunks)
                continue

            # 检查加上这个句子是否会超过最大长度
            if current_length + sentence_len > self.max_chunk_size:
                # 保存当前块
                if current_chunk:
                    chunk_text = ''.join(current_chunk)
                    if len(chunk_text) >= self.min_chunk_size:
                        chunks.append(chunk_text)
                    elif not chunks:
                        # 第一个块太小则保留
                        chunks.append(chunk_text)

                # 开始新块
                current_chunk = [sentence]
                current_length = sentence_len
            else:
                current_chunk.append(sentence)
                current_length += sentence_len

        # 处理最后一个块
        if current_chunk:
            chunk_text = ''.join(current_chunk)
            if len(chunk_text) >= self.min_chunk_size or not chunks:
                chunks.append(chunk_text)

        return chunks if chunks else [text] if text else []

    def _split_into_sentences(self, text: str) -> List[str]:
        """将文本分割成句子"""
        # 使用正则按句子分隔符分割
        pattern = '|'.join(re.escape(sep) for sep in self.sentence_separators)
        parts = re.split(pattern, text)

        # 过滤空白内容并清理
        sentences = []
        for part in parts:
            cleaned = part.strip()
            if cleaned:
                sentences.append(cleaned)
        return sentences

    def _split_long_sentence(self, sentence: str) -> List[str]:
        """切割长句子"""
        chunks = []
        # 按标点和空格切割
        parts = re.split(r'[,，、:：]', sentence)
        current = []
        current_len = 0

        for part in parts:
            part_len = len(part)
            if current_len + part_len > self.max_chunk_size:
                if current:
                    chunks.append(''.join(current))
                    current = []
                    current_len = 0
            current.append(part)
            current_len += part_len

        if current:
            chunks.append(''.join(current))

        return chunks if chunks else [sentence[:self.max_chunk_size]]

    def get_name(self) -> str:
        return f"semantic_{self.min_chunk_size}_{self.max_chunk_size}"


class DocumentStructureChunking(ChunkingStrategy):
    """
    文档结构分块 - 基于标题、段落等文档结构的智能分块
    保留文档的层次结构信息
    """

    def __init__(
        self,
        max_chunk_size: int = 800,
        overlap: int = 50
    ):
        self.max_chunk_size = max_chunk_size
        self.overlap = overlap

    def split(self, text: str) -> List[str]:
        """基于文档结构的分块"""
        # 识别标题行（以 # 开头或全大写或特定模式）
        lines = text.split('\n')
        chunks = []
        current_chunk_lines = []
        current_length = 0

        for line in lines:
            line_stripped = line.strip()
            if not line_stripped:
                continue

            line_length = len(line_stripped)

            # 检测是否为标题行
            # M29.2 (2026-06-15): 扩展覆盖括号包数字 / 汉字的二级标题格式 —
            # 精准停车功能文档.docx 大量 `（一）医院场景` / `（1）` / `（a）`
            # 段被 original 正则吞成 21 字符孤立 chunk。增加 4 条正则后这些
            # 都被识别为 heading,与正文分块。
            is_heading = (
                line_stripped.startswith('#') or
                (line_stripped.isupper() and len(line_stripped) < 100) or
                re.match(r'^[一二三四五六七八九十]+[、.。]', line_stripped) or
                re.match(r'^[一二三四五六七八九十]+[）)]', line_stripped) or
                re.match(r'^[（(][一二三四五六七八九十]+[）)]', line_stripped) or
                re.match(r'^[（(]\d+[）)]', line_stripped) or
                re.match(r'^[（(][a-zA-Z]+[）)]', line_stripped) or
                re.match(r'^\d+[.。]', line_stripped)
            )

            # 如果是标题行且当前块不为空，考虑切割
            if is_heading and current_chunk_lines:
                chunk_text = '\n'.join(current_chunk_lines)
                if chunk_text.strip():
                    chunks.append(chunk_text)

                # 处理重叠
                if self.overlap > 0 and len(current_chunk_lines) > 1:
                    overlap_lines = current_chunk_lines[-1:]
                    current_chunk_lines = overlap_lines
                    current_length = sum(len(l) for l in current_chunk_lines)
                else:
                    current_chunk_lines = []
                    current_length = 0

            # 检查当前块大小
            if current_length + line_length > self.max_chunk_size and current_chunk_lines:
                chunk_text = '\n'.join(current_chunk_lines)
                if chunk_text.strip():
                    chunks.append(chunk_text)
                current_chunk_lines = []
                current_length = 0

            current_chunk_lines.append(line)
            current_length += line_length

        # 处理最后一个块
        if current_chunk_lines:
            chunk_text = '\n'.join(current_chunk_lines)
            if chunk_text.strip():
                chunks.append(chunk_text)

        return chunks if chunks else [text] if text else []

    def get_name(self) -> str:
        return f"document_structure_{self.max_chunk_size}"


class ChunkingService:
    """分块服务 - 统一管理多种分块策略"""

    STRATEGIES = {
        "fixed": FixedSizeChunking,
        "semantic": SemanticChunking,
        "document_structure": DocumentStructureChunking,
    }

    def __init__(self, default_strategy: str = "fixed"):
        self.default_strategy = default_strategy
        self._strategy_cache: Dict[str, ChunkingStrategy] = {}

    def get_strategy(
        self,
        strategy_name: str = None,
        **kwargs
    ) -> ChunkingStrategy:
        """获取分块策略实例"""
        strategy_name = strategy_name or self.default_strategy

        if strategy_name == "fixed":
            return FixedSizeChunking(
                chunk_size=kwargs.get("chunk_size", 500),
                chunk_overlap=kwargs.get("chunk_overlap", 50)
            )
        elif strategy_name == "semantic":
            return SemanticChunking(
                min_chunk_size=kwargs.get("min_chunk_size", 200),
                max_chunk_size=kwargs.get("max_chunk_size", 800),
                sentence_separators=kwargs.get("sentence_separators")
            )
        elif strategy_name == "document_structure":
            return DocumentStructureChunking(
                max_chunk_size=kwargs.get("max_chunk_size", 800),
                overlap=kwargs.get("overlap", 50)
            )
        else:
            # 默认使用固定大小分块
            return FixedSizeChunking()

    def split_text(
        self,
        text: str,
        strategy_name: str = None,
        **kwargs
    ) -> List[str]:
        """分割文本"""
        strategy = self.get_strategy(strategy_name, **kwargs)
        return strategy.split(text)

    def split_with_metadata(
        self,
        text: str,
        strategy_name: str = None,
        **kwargs
    ) -> List[Dict[str, Any]]:
        """分割文本并返回带元数据的结果"""
        strategy = self.get_strategy(strategy_name, **kwargs)
        chunks = strategy.split(text)

        return [
            {
                "content": chunk,
                "chunk_index": i,
                "strategy": strategy.get_name(),
                "length": len(chunk)
            }
            for i, chunk in enumerate(chunks)
        ]

    @staticmethod
    def get_available_strategies() -> List[Dict[str, str]]:
        """获取可用的分块策略列表"""
        return [
            {
                "name": "fixed",
                "label": "固定大小分块",
                "description": "传统的重叠窗口分块，简单高效"
            },
            {
                "name": "semantic",
                "label": "语义分块",
                "description": "基于句子边界的智能分块，保持语义完整"
            },
            {
                "name": "document_structure",
                "label": "文档结构分块",
                "description": "基于标题和段落结构，保留文档层次"
            }
        ]


# 全局单例
_chunking_service: Optional[ChunkingService] = None


def get_chunking_service() -> ChunkingService:
    """获取分块服务单例"""
    global _chunking_service
    if _chunking_service is None:
        _chunking_service = ChunkingService()
    return _chunking_service
