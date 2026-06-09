import pytest
from src.file_research.parser import chunk_text, decode_text_file, validate_filename


def test_validate_filename_valid():
    # 验证常规路径及后缀
    assert validate_filename("folder/subfolder/readme.md") == "readme.md"
    assert validate_filename("main.py") == "main.py"


def test_validate_filename_invalid():
    # 验证不支持的扩展名直接抛错
    with pytest.raises(ValueError) as exc_info:
        validate_filename("dangerous.exe")
    assert "不支持的文件类型" in str(exc_info.value)


def test_decode_text_file_success():
    # 验证正常解码
    content = b"hello world\nthis is a test."
    parsed = decode_text_file("test.txt", content)
    assert parsed.filename == "test.txt"
    assert parsed.text == "hello world\nthis is a test."
    assert parsed.size_bytes == len(content)


def test_decode_text_file_empty():
    # 验证空文件保护
    with pytest.raises(ValueError) as exc_info:
        decode_text_file("empty.txt", b"   \n   ")
    assert "文件内容为空" in str(exc_info.value)


def test_decode_text_file_oversized():
    # 验证超大文件保护 (超过 5MB)
    huge_data = b"a" * (5 * 1024 * 1024 + 1)
    with pytest.raises(ValueError) as exc_info:
        decode_text_file("huge.txt", huge_data)
    assert "文件超过 5MB 限制" in str(exc_info.value)


def test_chunk_text_basic():
    # 验证基本切块逻辑
    text = "0123456789"
    chunks = chunk_text(text, chunk_size=5, overlap=0)
    assert chunks == ["01234", "56789"]


def test_chunk_text_keeps_overlap():
    # 验证重叠区机制：第二块的起点应该是第一块终点往前退 overlap 长度
    text = "0123456789"
    # 第一块: 0-6 -> "012345"
    # 第二块从 6-2=4 开始到 10 -> "456789"
    chunks = chunk_text(text, chunk_size=6, overlap=2)
    assert chunks == ["012345", "456789"]


def test_chunk_text_whitespace_handling():
    # 验证首尾空格裁剪
    text = "  hello  \n\n  world  "
    chunks = chunk_text(text, chunk_size=100, overlap=0)
    assert chunks == ["hello  \n\n  world"]
