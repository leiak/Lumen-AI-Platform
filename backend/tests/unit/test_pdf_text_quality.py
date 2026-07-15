"""
Unit tests for BaseParser._looks_like_pdf_byte_stream.

This is the defense layer that catches Docling's worst failure mode:
returning the raw PDF byte stream as "extracted text" when the font's
ToUnicode CMap is missing or broken (typical of Chrome-headless-printed
PDFs). Without this check, the empty/non-empty guard in
document_parser / document_tasks would not notice the garbage and the
chunks would be embedded + indexed anyway.

The detection rules (any one fires):
  1. text starts with ``%PDF-``
  2. first 2000 chars contain 2+ PDF internal markers
     (FlateDecode / endobj / endstream / MediaBox / /Type /Page / /Encoding)
  3. first 2000 chars have > 5% non-printable control characters
     (excluding \\n, \\r, \\t)

Edge cases: empty / very short text must NOT be flagged (avoids
false positives on titles, headers, or "no text found" returns).
"""
from lumen_services.parsers import GeneralParser


def _parser():
    # Use a concrete subclass to exercise the inherited method.
    return GeneralParser()


def test_detects_pdf_header():
    """Text starting with %PDF- is byte-stream garbage."""
    p = _parser()
    assert p._looks_like_pdf_byte_stream("%PDF-1.4\n1 0 obj\n<<>>endobj\n") is True


def test_detects_flatedecode_endobj():
    """Text containing 2+ PDF internal markers is byte-stream garbage."""
    p = _parser()
    # Pad with normal text BEFORE the markers so we know the markers
    # themselves (not just the header rule) are what trip detection.
    sample = (
        "Some leading text that looks normal " * 5
        + "FlateDecode endobj endstream MediaBox /Type /Page /Encoding"
        + " trailing " * 20
    )
    assert p._looks_like_pdf_byte_stream(sample) is True


def test_detects_non_printable_ratio():
    """Heavy non-printable control chars = byte stream."""
    p = _parser()
    # \x00, \x01, \x02, \x03, \x04, \x05 ... > 5% of 2000 chars
    sample = "\x00" * 200 + "normal text content " * 80
    assert p._looks_like_pdf_byte_stream(sample) is True


def test_normal_chinese_passes():
    """Plain Chinese text must NOT be flagged as garbage."""
    p = _parser()
    sample = (
        "产品表: 产品id, 产品名称, 价格, 库存, 分类id, 上架时间, 状态, "
        "描述, 图片URL, 商家id, 创建时间, 更新时间。\n"
        "订单表: 订单id, 用户id, 收货地址id, 总金额, 实付金额, 支付方式, "
        "订单状态, 下单时间, 支付时间, 发货时间, 完成时间, 备注。\n"
    ) * 5
    assert p._looks_like_pdf_byte_stream(sample) is False


def test_normal_english_passes():
    """Plain English paragraphs must NOT be flagged as garbage."""
    p = _parser()
    sample = (
        "This is a normal English paragraph about a software system. "
        "It contains multiple sentences with typical English vocabulary. "
        "Numbers like 12345 and symbols like $100 are common. "
    ) * 10
    assert p._looks_like_pdf_byte_stream(sample) is False


def test_empty_passes():
    """Empty text — let the downstream empty-string guard handle it."""
    p = _parser()
    assert p._looks_like_pdf_byte_stream("") is False


def test_short_text_passes():
    """Text under 50 chars is too small to be PDF byte stream; do not flag.

    Avoids false-positives on titles, single-line documents, or
    'no extractable text' empty-ish returns that happen to contain
    a stray keyword.
    """
    p = _parser()
    assert p._looks_like_pdf_byte_stream("FlateDecode endobj endstream") is False
    assert p._looks_like_pdf_byte_stream("Short PDF title") is False
