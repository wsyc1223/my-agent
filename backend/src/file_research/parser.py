from dataclasses import dataclass
from pathlib import Path

# 第一版只支持纯文本类型后缀，确保安全与解析可靠性
ALLOWED_SUFFIXES = {".txt", ".md", ".py", ".ts", ".vue", ".js", ".json", ".html", ".css", ".log", ".csv"}
MAX_FILE_BYTES = 5 * 1024 * 1024  # 限制单文件最大 5MB，防范大文件内存崩溃 (DoS)


@dataclass
class ParsedFile:
    filename: str
    text: str
    size_bytes: int


def validate_filename(filename: str) -> str:
    """
    提取纯文件名，防止路径穿越攻击 (../../etc/passwd)，并验证后缀白名单
    """
    safe_name = Path(filename).name
    suffix = Path(safe_name).suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise ValueError(f"不支持的文件类型: {suffix}")
    return safe_name


def decode_text_file(filename: str, data: bytes) -> ParsedFile:
    """
    解码字节流为 UTF-8 文本，并应用文件大小和内容完整性约束
    """
    safe_name = validate_filename(filename)
    if len(data) > MAX_FILE_BYTES:
        raise ValueError("文件超过 5MB 限制")
 
    # 使用 errors="replace" 柔性处理非法编码字符，防止解码意外崩溃
    text = data.decode("utf-8", errors="replace").strip()
    if not text:
        raise ValueError("文件内容为空")
    
    return ParsedFile(filename=safe_name, text=text, size_bytes=len(data))


def chunk_text(text: str, chunk_size: int = 1200, overlap: int = 180) -> list[str]:
    """
    将文本划分为固定大小的切块，并在相邻切块间保留重叠区 (Overlap) 以维护语义连贯性
    """
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    chunks: list[str] = []
    start = 0
    while start < len(normalized):
        end = min(start + chunk_size, len(normalized))
        chunk = normalized[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end == len(normalized):
            break
        # 回退 overlap 长度，为下一个切块准备起始点
        start = max(0, end - overlap)
    return chunks
