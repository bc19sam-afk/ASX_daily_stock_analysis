# -*- coding: utf-8 -*-
"""
===================================
格式化工具模块
===================================

提供各种内容格式化工具函数，用于将通用格式转换为平台特定格式。
"""

import re
import time
from typing import List, Callable

import markdown2


_BASE_CSS = """
            * {
                box-sizing: border-box;
            }
            body {
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
                font-size: 15px;
                line-height: 1.58;
                margin: 0 auto;
                background: #f7f9fc;
                color: #1f2937;
                -webkit-text-size-adjust: 100%;
                text-rendering: optimizeLegibility;
            }
            h1 {
                border: 1px solid #d6dee8;
                border-radius: 8px;
                background: #ffffff;
                box-shadow: 0 1px 2px rgba(15, 23, 42, 0.05);
            }
            h2 {
                letter-spacing: 0;
            }
            h3 {
                font-size: 16px;
                letter-spacing: 0;
            }
            blockquote {
                color: #334155;
                border-left: 4px solid #2563eb;
                padding: 8px 12px;
                background: #eef6ff;
                border-radius: 6px;
            }
            table {
                border-collapse: separate;
                border-spacing: 0;
                width: 100%;
                font-size: 13px;
                table-layout: auto;
                background: #ffffff;
                border-radius: 8px;
                box-shadow: 0 1px 2px rgba(15, 23, 42, 0.05);
                color: #1f2937;
            }
            th, td {
                border: 0;
                text-align: left;
                vertical-align: top;
                line-height: 1.5;
                overflow-wrap: anywhere;
                word-break: break-word;
            }
            th:last-child, td:last-child {
                border-right: 0;
            }
            th {
                background: #eef2f7;
                color: #111827;
                border-bottom: 2px solid #cbd5e1;
            }
            strong {
                color: #0f172a;
            }
            td:first-child {
                font-weight: 600;
                color: #0f172a;
            }
            td {
                max-width: 360px;
            }
            td:nth-child(n+2) {
                font-variant-numeric: tabular-nums;
            }
            tr:last-child td {
                border-bottom: 0;
            }
            code {
                font-family: SFMono-Regular, Consolas, "Liberation Mono", Menlo, monospace;
                border-radius: 3px;
            }
            pre {
                padding: 12px;
                background-color: #f6f8fa;
            }
            ul, ol {
                padding-left: 20px;
            }
            li {
                margin: 2px 0;
            }
        """


_EMAIL_CSS = """
            body {
                color: #1f2937;
                padding: 18px;
                max-width: 920px;
            }
            h1 {
                font-size: 22px;
                line-height: 1.25;
                border-left: 6px solid #2563eb;
                padding: 14px 16px;
                margin: 0 0 18px 0;
                color: #0f172a;
            }
            h2 {
                font-size: 18px;
                line-height: 1.3;
                border: 0;
                border-left: 4px solid #2563eb;
                border-bottom: 1px solid #d8e1ee;
                border-radius: 0;
                background: transparent;
                box-shadow: none;
                padding: 3px 0 7px 10px;
                margin: 26px 0 12px 0;
                color: #0f172a;
            }
            h3 {
                font-size: 15px;
                line-height: 1.35;
                margin: 18px 0 7px 0;
                color: #111827;
            }
            p {
                margin-top: 0;
                margin-bottom: 9px;
            }
            table {
                margin: 12px 0 18px 0;
                display: block;
                width: 100%;
                max-width: 100%;
                overflow-x: auto;
                border: 1px solid #d6dee8;
                border-radius: 8px;
                -webkit-overflow-scrolling: touch;
            }
            th, td {
                border-right: 1px solid #e2e8f0;
                border-bottom: 1px solid #e2e8f0;
                padding: 8px 10px;
            }
            th {
                background-color: #edf2f7;
                font-weight: 700;
                white-space: nowrap;
            }
            tr:nth-child(2n) {
                background-color: #f8fafc;
            }
            tr:hover {
                background-color: #f1f7ff;
            }
            strong {
                color: #111827;
            }
            blockquote {
                margin: 0 0 12px 0;
            }
            code {
                padding: 0.2em 0.4em;
                margin: 0;
                font-size: 85%;
                background-color: rgba(27,31,35,0.05);
            }
            pre {
                overflow: auto;
                line-height: 1.45;
                border-radius: 3px;
                margin-bottom: 10px;
                white-space: pre-wrap;
                word-break: break-word;
            }
            hr {
                height: 1px;
                padding: 0;
                margin: 22px 0;
                background-color: #d8e1ee;
                border: 0;
            }
            ul, ol {
                margin: 6px 0 12px 0;
            }
            li {
                margin: 3px 0;
            }
            @media (max-width: 640px) {
                body {
                    padding: 12px;
                    font-size: 14px;
                }
                h1 {
                    font-size: 20px;
                    padding: 12px 14px;
                }
                h2 {
                    font-size: 17px;
                    margin-top: 22px;
                }
                table {
                    font-size: 12px;
                    margin: 10px 0;
                }
                th, td {
                    padding: 6px 8px;
                }
                td {
                    max-width: 260px;
                }
            }
        """


_ARCHIVE_CSS = """
            @page {
                margin: 14mm;
            }
            * {
                box-sizing: border-box;
            }
            body {
                color: #1f2937;
                max-width: 1040px;
                padding: 24px;
            }
            h1 {
                font-size: 25px;
                line-height: 1.25;
                margin: 0 0 18px 0;
                padding: 16px 18px;
                border-left: 6px solid #2563eb;
                color: #111827;
            }
            h2 {
                font-size: 19px;
                line-height: 1.3;
                margin: 28px 0 12px 0;
                padding: 4px 0 8px 12px;
                border: 0;
                border-left: 5px solid #2563eb;
                border-bottom: 1px solid #d8e1ee;
                border-radius: 0;
                background: transparent;
                box-shadow: none;
                color: #111827;
                break-after: avoid;
            }
            h3 {
                font-size: 16px;
                margin: 20px 0 8px 0;
                break-after: avoid;
            }
            p {
                margin: 0 0 8px 0;
            }
            blockquote {
                margin: 8px 0 12px 0;
            }
            table {
                margin: 12px 0 18px 0;
                display: block;
                width: 100%;
                max-width: 100%;
                overflow-x: auto;
                border: 1px solid #d0d7de;
                border-radius: 8px;
                break-inside: avoid;
                -webkit-overflow-scrolling: touch;
            }
            th, td {
                border-right: 1px solid #d0d7de;
                border-bottom: 1px solid #d0d7de;
                padding: 8px 10px;
            }
            th {
                font-weight: 700;
                white-space: nowrap;
                background: #edf2f7;
            }
            tr:nth-child(2n) {
                background: #f8fafc;
            }
            ul, ol {
                margin: 6px 0 12px 0;
                padding-left: 22px;
            }
            li {
                margin: 3px 0;
            }
            hr {
                border: 0;
                border-top: 1px solid #e5e7eb;
                margin: 18px 0;
                height: 0;
            }
            code {
                font-size: 90%;
                background: #f3f4f6;
                padding: 1px 4px;
            }
            pre {
                white-space: pre-wrap;
                word-break: break-word;
                border: 1px solid #d0d7de;
                border-radius: 4px;
            }
            img {
                max-width: 100%;
                height: auto;
            }
            @media print {
                body {
                    max-width: none;
                    padding: 0;
                }
                a {
                    color: inherit;
                    text-decoration: none;
                }
                table, blockquote, pre {
                    break-inside: avoid;
                }
                table {
                    display: table;
                    overflow: visible;
                }
            }
            @media screen and (max-width: 640px) {
                body {
                    padding: 12px;
                    font-size: 14px;
                }
                h1 {
                    font-size: 21px;
                }
                h2 {
                    font-size: 17px;
                    margin-top: 22px;
                }
                table {
                    display: block;
                    overflow-x: auto;
                    font-size: 12px;
                }
                th, td {
                    padding: 6px 8px;
                }
                td {
                    max-width: 260px;
                }
            }
        """


def markdown_to_html_document(markdown_text: str) -> str:
    """
    Convert Markdown to a complete HTML document (for email, md2img, etc.).

    Uses markdown2 with table and code block support, wraps with inline CSS
    for compact, readable layout. Reused by notification email and md2img.

    Args:
        markdown_text: Raw Markdown content.

    Returns:
        Full HTML document string with DOCTYPE, head, and body.
    """
    html_content = markdown2.markdown(
        markdown_text,
        extras=["tables", "fenced-code-blocks", "break-on-newline", "cuddled-lists"],
    )

    css_style = _BASE_CSS + _EMAIL_CSS

    return f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <style>
                {css_style}
            </style>
        </head>
        <body>
            {html_content}
        </body>
        </html>
        """


def markdown_to_archive_html_document(markdown_text: str) -> str:
    """
    Convert Markdown to a standalone, print-friendly HTML archive document.

    The archive stays text-based (copyable/selectable) and avoids fixed-height
    containers so future HTML -> PDF conversion does not create blank tail pages.
    """
    html_content = markdown2.markdown(
        markdown_text,
        extras=["tables", "fenced-code-blocks", "break-on-newline", "cuddled-lists"],
    )

    css_style = _BASE_CSS + _ARCHIVE_CSS

    return f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>ASX Daily Decision Report</title>
    <style>
{css_style}
    </style>
</head>
<body>
{html_content}
</body>
</html>
"""


def format_feishu_markdown(content: str) -> str:
    """
    将通用 Markdown 转换为飞书 lark_md 更友好的格式
    
    转换规则：
    - 飞书不支持 Markdown 标题（# / ## / ###），用加粗代替
    - 引用块使用前缀替代
    - 分隔线统一为细线
    - 表格转换为条目列表
    
    Args:
        content: 原始 Markdown 内容
        
    Returns:
        转换后的飞书 Markdown 格式内容
        
    Example:
        >>> markdown = "# 标题\\n> 引用\\n| 列1 | 列2 |"
        >>> formatted = format_feishu_markdown(markdown)
        >>> print(formatted)
        **标题**
        💬 引用
        • 列1：值1 | 列2：值2
    """
    def _flush_table_rows(buffer: List[str], output: List[str]) -> None:
        """将表格缓冲区中的行转换为飞书格式"""
        if not buffer:
            return

        def _parse_row(row: str) -> List[str]:
            """解析表格行，提取单元格"""
            raw = row.strip()
            if raw.startswith('|'):
                raw = raw[1:]
            if raw.endswith('|'):
                raw = raw[:-1]
            # 仅按未转义的竖线分列；保留单元格中的 \| 字面量
            cells = [c.strip() for c in re.split(r'(?<!\\)\|', raw)]
            return [c.replace(r'\|', '|') for c in cells]

        rows = []
        for raw in buffer:
            # 跳过分隔行（如 |---|---|）
            if re.match(r'^\s*\|?\s*[:-]+\s*(\|\s*[:-]+\s*)+\|?\s*$', raw):
                continue
            parsed = _parse_row(raw)
            if parsed:
                rows.append(parsed)

        if not rows:
            return

        header = rows[0]
        data_rows = rows[1:] if len(rows) > 1 else []
        for row in data_rows:
            pairs = []
            for idx, cell in enumerate(row):
                key = header[idx] if idx < len(header) else f"列{idx + 1}"
                pairs.append(f"{key}：{cell}")
            output.append(f"• {' | '.join(pairs)}")

    lines = []
    table_buffer: List[str] = []

    for raw_line in content.splitlines():
        line = raw_line.rstrip()

        # 处理表格行
        if line.strip().startswith('|'):
            table_buffer.append(line)
            continue

        # 刷新表格缓冲区
        if table_buffer:
            _flush_table_rows(table_buffer, lines)
            table_buffer = []

        # 转换标题（# ## ### 等）
        if re.match(r'^#{1,6}\s+', line):
            title = re.sub(r'^#{1,6}\s+', '', line).strip()
            line = f"**{title}**" if title else ""
        # 转换引用块
        elif line.startswith('> '):
            quote = line[2:].strip()
            line = f"💬 {quote}" if quote else ""
        # 转换分隔线
        elif line.strip() == '---':
            line = '────────'
        # 转换列表项
        elif line.startswith('- '):
            line = f"• {line[2:].strip()}"

        lines.append(line)

    # 处理末尾的表格
    if table_buffer:
        _flush_table_rows(table_buffer, lines)

    return "\n".join(lines).strip()


def _chunk_by_lines(content: str, max_bytes: int, send_func: Callable[[str], bool]) -> bool:
    """
    强制按行分割发送（无法智能分割时的 fallback）
    
    Args:
        content: 完整消息内容
        max_bytes: 单条消息最大字节数
        send_func: 发送单条消息的函数
        
    Returns:
        是否全部发送成功
    """
    chunks = []
    current_chunk = ""
    
    # 按行分割，确保不会在多字节字符中间截断
    lines = content.split('\n')
    
    for line in lines:
        test_chunk = current_chunk + ('\n' if current_chunk else '') + line
        if len(test_chunk.encode('utf-8')) > max_bytes - 100:  # 预留空间给分页标记
            if current_chunk:
                chunks.append(current_chunk)
            current_chunk = line
        else:
            current_chunk = test_chunk
    
    if current_chunk:
        chunks.append(current_chunk)
    
    total_chunks = len(chunks)
    success_count = 0
    
    for i, chunk in enumerate(chunks):
        # 添加分页标记
        page_marker = f"\n\n📄 ({i+1}/{total_chunks})" if total_chunks > 1 else ""
        
        try:
            if send_func(chunk + page_marker):
                success_count += 1
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"飞书第 {i+1}/{total_chunks} 批发送异常: {e}")
        
        # 批次间隔，避免触发频率限制
        if i < total_chunks - 1:
            time.sleep(1)
    
    return success_count == total_chunks


def chunk_feishu_content(content: str, max_bytes: int, send_func: Callable[[str], bool]) -> bool:
    """
    将超长内容分段发送到飞书
    
    智能分割策略：
    1. 优先按 "---" 分隔（股票之间的分隔线）
    2. 其次按 "### " 标题分割（每只股票的标题）
    3. 最后按行强制分割
    
    Args:
        content: 完整消息内容
        max_bytes: 单条消息最大字节数
        send_func: 发送单条消息的函数，接收内容字符串，返回是否成功
        
    Returns:
        是否全部发送成功
    """
    def get_bytes(s: str) -> int:
        """获取字符串的 UTF-8 字节数"""
        return len(s.encode('utf-8'))
    
    def _truncate_to_bytes(text: str, max_bytes: int) -> str:
        """按字节截断文本，确保不会在多字节字符中间截断"""
        encoded = text.encode('utf-8')
        if len(encoded) <= max_bytes:
            return text
        
        # 从最大字节数开始向前查找，找到完整的 UTF-8 字符边界
        truncated = encoded[:max_bytes]
        while truncated and (truncated[-1] & 0xC0) == 0x80:
            truncated = truncated[:-1]
        
        return truncated.decode('utf-8', errors='ignore')
    
    # 智能分割：优先按 "---" 分隔（股票之间的分隔线）
    # 如果没有分隔线，按 "### " 标题分割（每只股票的标题）
    if "\n---\n" in content:
        sections = content.split("\n---\n")
        separator = "\n---\n"
    elif "\n### " in content:
        # 按 ### 分割，但保留 ### 前缀
        parts = content.split("\n### ")
        sections = [parts[0]] + [f"### {p}" for p in parts[1:]]
        separator = "\n"
    else:
        # 无法智能分割，按行强制分割
        return _chunk_by_lines(content, max_bytes, send_func)
    
    chunks = []
    current_chunk = []
    current_bytes = 0
    separator_bytes = get_bytes(separator)
    
    for section in sections:
        section_bytes = get_bytes(section) + separator_bytes
        
        # 如果单个 section 就超长，需要强制截断
        if section_bytes > max_bytes:
            # 先发送当前积累的内容
            if current_chunk:
                chunks.append(separator.join(current_chunk))
                current_chunk = []
                current_bytes = 0
            
            # 强制截断这个超长 section（按字节截断）
            truncated = _truncate_to_bytes(section, max_bytes - 200)
            truncated += "\n\n...(本段内容过长已截断)"
            chunks.append(truncated)
            continue
        
        # 检查加入后是否超长
        if current_bytes + section_bytes > max_bytes:
            # 保存当前块，开始新块
            if current_chunk:
                chunks.append(separator.join(current_chunk))
            current_chunk = [section]
            current_bytes = section_bytes
        else:
            current_chunk.append(section)
            current_bytes += section_bytes
    
    # 添加最后一块
    if current_chunk:
        chunks.append(separator.join(current_chunk))
    
    # 分批发送
    total_chunks = len(chunks)
    success_count = 0
    
    for i, chunk in enumerate(chunks):
        # 添加分页标记
        if total_chunks > 1:
            page_marker = f"\n\n📄 ({i+1}/{total_chunks})"
            chunk_with_marker = chunk + page_marker
        else:
            chunk_with_marker = chunk
        
        try:
            if send_func(chunk_with_marker):
                success_count += 1
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"飞书第 {i+1}/{total_chunks} 批发送异常: {e}")
        
        # 批次间隔，避免触发频率限制
        if i < total_chunks - 1:
            time.sleep(1)
    
    return success_count == total_chunks
