import httpx
from langchain_core.tools import tool
from datetime import datetime
from bs4 import BeautifulSoup
from src.config import settings
import ipaddress, socket
from urllib.parse import urlparse

def is_safe_url(url: str) -> bool:
    # 解析 url
    parsed = urlparse(url)

    # 限制协议必须是 http 或者是 https
    # 防范利用 file:// 读取本地文件(如 /etc/passwd) 或 gopher://, ftp://等非安全协议攻击
    if parsed.scheme not in ("http", "https"):
        return False

    # 必须包含主机名
    if not parsed.hostname:
        return False
 
    try:
        ip = ipaddress.ip_address(socket.gethostbyname(parsed.hostname))
    except (socket.gaierror, ValueError):
        return False
    if ip.is_private or ip.is_loopback or ip.is_reserved or ip.is_link_local:
        return False
    return True


TAVILY_API_KEY=settings.TAVILY_API_KEY

@tool
def get_weather(city: str) -> str:
    """
        根据城市名称来查询当前的天气情况, 温度, 以及体感温度。

        参数: city(str): 城市名称
        返回: str: 当前天气情况的描述, 包括天气状况, 温度, 以及体感温度。
    """
    return f"{city}现在是天气晴朗的，温度是25摄氏度，体感温度是27摄氏度。"

@tool
def calculator(a: float, b: float, op: str) -> str:
    """
        执行基础的四则运算。

        参数: a(float): 第一个数字
              b(float): 第二个数字
              op(str): 运算类型，可选值: add(加), sub(减), mul(乘), div(除)
        返回: str: 计算结果
    """
    if op == "add":
        return f"{a} + {b} = {a + b}"
    elif op == "sub":
        return f"{a} - {b} = {a - b}"
    elif op == "mul":
        return f"{a} × {b} = {a * b}"
    elif op == "div":
        if b == 0:
            return "错误: 除数不能为零"
        return f"{a} ÷ {b} = {a / b}"
    else:
        return f"错误: 不支持的运算类型 '{op}'，可选 add/sub/mul/div"

@tool
def get_current_time() -> str:
    """
        获取当前的日期和时间。

        参数: 无
        返回: str: 当前日期和时间的字符串表示
    """
    return datetime.now().strftime("当前时间是 %Y年%m月%d日 %H:%M:%S")

@tool
async def search_web(query: str) -> str:
    """
        搜索互联网获取最新信息，当需要实时数据、新闻或者不确定事实的时候后使用。

        参数: query(str): 搜索的关键词
        返回: result(str): 返回的结果
    """
    tavily_api_key = TAVILY_API_KEY
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://api.tavily.com/search",
            json = {
                "api_key": tavily_api_key,
                "query": query,
                "max_results": 5,
                "include_answers": True
            },
            timeout=10.0
        )
        resp.raise_for_status()
        data = resp.json()

    results = []
    if data.get("answer"):
        results.append(f"摘要: {data['answer']}")
    for r in data.get("results", []):
        results.append(f"- {r['title']}: {r['content'][:200]}")
    return "\n".join(results)

@tool
async def fetch_url(url: str) -> str:
    """
        获取指定网页的完整内容，当搜索摘要不够详细、需要阅读全文时使用, 
        如果连续两次都返回错误，说明目标网站有反爬保护，请停止尝试，并且说明情况。

        参数: url(str): 网页的url
        返回: result(str): 网页的详细内容
    """
    try:
        if not is_safe_url(url):
            return f"错误: 安全策略禁止访问该 URL ({url}), 不允许内网地址或非 HTTP 协议"
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, timeout=10.0, headers={
                "User-Agent": "Mozilla/5.0 (compatible; LangChainBot/1.0)"
            })

            resp.raise_for_status()
            html_text = resp.text
    except httpx.TimeoutException:
        return f"错误: 请求网页超时 (10秒)，网址 {url} 可能无法访问或响应过慢"
    except httpx.ConnectError:
        return f"错误: 无法连接到 {url}，请检查网址是否正确，或该网站可能被防火墙屏蔽"
    except httpx.HTTPStatusError as e:
        return f"错误: 网页返回了错误的状态码 {e.response.status_code}，网址 {url} 可能不存在或需要登录"
    except httpx.RequestError as e:
        return f"错误: 请求网页 {url} 时发生网络错误: {str(e)}"

    soup = BeautifulSoup(html_text, "html.parser")
    text = soup.get_text(separator="\n", strip=True)
    if len(text.strip()) < 100:
        return f"无法获取该页面内容（可能有反爬虫保护），建议用 search_web 搜索相关信息"
    return text[:3000]

tools = [get_weather, calculator, search_web, get_current_time, fetch_url]
