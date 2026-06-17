import pytest
from src.file_research.parser import chunk_text_with_line

def test_chunk_text_with_line_basic():
    """
    测试点 1: 验证基础换行文本切块后，行号是否能够计算精准
    """
    text = "line1\nline2\nline3\nline4\nline5"

    # 模拟切块： 设置切块大小较小（如 12 字符， 刚好可以把前两行切成第一块）
    chunks = chunk_text_with_line(text, chunk_size=12, overlap=3)

    # 验证第一个切片： 内容应该是 "line1\line2", 它在原文的第 1 行到第 2 行之间
    assert chunks[0].content == "line1\nline2"
    assert chunks[0].start_line == 1
    assert chunks[0].end_line ==  2


def test_chunk_text_with_line_whitespace_boundary():
    """
    测试点 2： 验证文件开头和结尾如果存在大量空格/空行，
    算法是否能够避开空行干扰，并精准定位到真实的物理行
    """
    # strip_me 在第 3 行， line5 在第 5 行
    long_text = "\n\n strip_me\nline4\nline5\n"

    chunks = chunk_text_with_line(long_text, chunk_size=100, overlap=0)

    # 验证经过 strip() 后的干净内容
    assert chunks[0].content == "strip_me\nline4\nline5"

    # 核心测试： 验证起止行号是否完美避开了开头的两个空行， 精确定位在第 3 行到第 5 行
    assert chunks[0].start_line == 3
    assert chunks[0].end_line == 5
    
print("测试通过")
