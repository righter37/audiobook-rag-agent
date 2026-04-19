#!/usr/bin/env python3
"""
听书Agent - Step 1
基于 s01_agent_loop，把工具换成听书场景。
agent_loop 本身一行没变，只换了 SYSTEM / TOOLS / TOOL_HANDLERS。
"""

import os
import json
import time
import httpx
import concurrent.futures
from pathlib import Path
from anthropic import Anthropic
from dotenv import load_dotenv

# 复用 learn-claude-code-main 的 .env（API Key、MODEL_ID、BASE_URL）
_env_path = os.path.join(os.path.dirname(__file__), "learn-claude-code-main", ".env")
load_dotenv(_env_path, override=True)

# 禁用系统代理：moonshot.cn 是国内地址，不需要代理
client = Anthropic(
    base_url=os.getenv("ANTHROPIC_BASE_URL"),
    http_client=httpx.Client(trust_env=False),
)
MODEL = os.environ["MODEL_ID"]

SUBAGENT_SYSTEM = """你是一个搜索+下载助手，独立完成单本书的搜索和下载。

步骤：
1. 用 search_book 搜索书名，指定 epub 格式
2. 从结果中选最合适的版本（epub 优先，同格式选文件最小的）
3. 用 download_file 下载

完成后一句话汇报：成功给出文件路径，失败说明原因。"""

SYSTEM = """你是一个听书助手，帮用户完成找书→下载→播放的完整流程。

流程：
1. 先用 todo 工具写下本次任务的步骤，标记第一步为 in_progress
2. 用 check_local 检查本地是否已有这本书
   - 有 → 直接用 play_book 播放，跳过搜索和下载
   - 没有 → 继续下面的流程
3. 用 search_book 搜索书籍，把结果展示给用户
4. 用户确认后，为每本书单独调用一个 task 工具，prompt 只需包含书名（子 Agent 会自行搜索+下载）。多本书同时发出多个 task，最多 3 个并发
5. 下载成功后，用 play_book 播放
6. 每完成一步，用 todo 更新进度

6. 用户问书里的问题时：
   - 先用 index_book 建立索引（若已建立则跳过）
   - 再用 ask_book 召回相关段落，根据段落内容回答

注意：
- 每步开始前把该步标记为 in_progress，完成后标记为 completed
- 下载前必须先得到用户确认
- play_book 的 file_path 必须是完整的 Windows 路径
- 用中文回复"""

# ── s06 上下文压缩：三层机制 ──
TRANSCRIPT_DIR = Path(__file__).parent / ".transcripts"
COMPACT_THRESHOLD = 20000  # token 估算超过这个值触发 auto_compact
KEEP_RECENT = 3             # micro_compact 保留最近几条 tool_result


def estimate_tokens(messages: list) -> int:
    """粗略估算 token 数：4个字符≈1个token"""
    return len(str(messages)) // 4


def micro_compact(messages: list) -> list:
    """
    Layer 1：把较早的 tool_result 替换成占位符，保留最近 KEEP_RECENT 条。
    每轮都跑，静默执行，不打扰用户。
    """
    tool_results = []
    for msg_idx, msg in enumerate(messages):
        if msg["role"] == "user" and isinstance(msg.get("content"), list):
            for part_idx, part in enumerate(msg["content"]):
                if isinstance(part, dict) and part.get("type") == "tool_result":
                    tool_results.append((msg_idx, part_idx, part))

    if len(tool_results) <= KEEP_RECENT:
        return messages

    # 建立 tool_use_id → tool_name 的映射
    tool_name_map = {}
    for msg in messages:
        if msg["role"] == "assistant":
            content = msg.get("content", [])
            if isinstance(content, list):
                for block in content:
                    if hasattr(block, "type") and block.type == "tool_use":
                        tool_name_map[block.id] = block.name

    # 把旧的 tool_result 替换成占位符
    for _, _, result in tool_results[:-KEEP_RECENT]:
        if isinstance(result.get("content"), str) and len(result["content"]) > 100:
            tool_id = result.get("tool_use_id", "")
            tool_name = tool_name_map.get(tool_id, "unknown")
            result["content"] = f"[Previous: used {tool_name}]"

    return messages


def auto_compact(messages: list) -> list:
    """
    Layer 2：token 超阈值时触发。
    把完整对话存档到 .transcripts/，然后让 LLM 总结，用摘要替换所有消息。
    """
    TRANSCRIPT_DIR.mkdir(exist_ok=True)
    transcript_path = TRANSCRIPT_DIR / f"transcript_{int(time.time())}.jsonl"
    with open(transcript_path, "w", encoding="utf-8") as f:
        for msg in messages:
            f.write(json.dumps(msg, default=str, ensure_ascii=False) + "\n")
    print(f"\033[33m[auto_compact] 对话已存档: {transcript_path}\033[0m")

    # 让 LLM 总结对话
    conversation_text = json.dumps(messages, default=str, ensure_ascii=False)[:60000]
    response = client.messages.create(
        model=MODEL,
        messages=[{"role": "user", "content":
            "请用中文总结以下对话，保留：1）已完成的操作，2）当前状态，3）关键信息（书名/路径/用户偏好）。简洁但不丢失关键细节。\n\n" + conversation_text}],
        max_tokens=1000,
    )
    summary = response.content[0].text
    print(f"\033[33m[auto_compact] 压缩完成，摘要长度: {len(summary)} 字\033[0m")

    return [
        {"role": "user",      "content": f"[对话已压缩，原始记录: {transcript_path}]\n\n{summary}"},
        {"role": "assistant", "content": "已获取上下文摘要，继续为您服务。"},
    ]


# ── TodoManager（来自 s03）──
class TodoManager:
    def __init__(self):
        self.items = []

    def update(self, items: list) -> str:
        validated = []
        in_progress_count = 0
        for i, item in enumerate(items):
            text = str(item.get("text", "")).strip()
            status = str(item.get("status", "pending")).lower()
            item_id = str(item.get("id", str(i + 1)))
            if status not in ("pending", "in_progress", "completed"):
                raise ValueError(f"invalid status '{status}'")
            if status == "in_progress":
                in_progress_count += 1
            validated.append({"id": item_id, "text": text, "status": status})
        if in_progress_count > 1:
            raise ValueError("只能有一个 in_progress 任务")
        self.items = validated
        rendered = self.render()
        print(f"\033[36m{rendered}\033[0m")  # 青色显示进度
        return rendered

    def render(self) -> str:
        if not self.items:
            return "No todos."
        markers = {"pending": "[ ]", "in_progress": "[>]", "completed": "[x]"}
        lines = [markers[t["status"]] + f" {t['text']}" for t in self.items]
        done = sum(1 for t in self.items if t["status"] == "completed")
        lines.append(f"({done}/{len(self.items)} 完成)")
        return "\n".join(lines)

TODO = TodoManager()

# ── 工具定义 ──
TOOLS = [
    {
        "name": "todo",
        "description": "更新任务进度列表，每步开始标记 in_progress，完成标记 completed",
        "input_schema": {
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id":     {"type": "string"},
                            "text":   {"type": "string"},
                            "status": {"type": "string", "enum": ["pending", "in_progress", "completed"]}
                        },
                        "required": ["id", "text", "status"]
                    }
                }
            },
            "required": ["items"]
        }
    },
    {
        "name": "check_local",
        "description": "检查本地 books/ 目录是否已有匹配的书籍文件，有则返回文件路径",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "书名关键词，模糊匹配"}
            },
            "required": ["title"]
        }
    },
    {
        "name": "search_book",
        "description": "搜索书籍，优先 Z-Library，备用鸠摩搜书。返回包含 download_url 的结果列表",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "书名，可加作者名提高精度"},
                "format": {
                    "type": "string",
                    "enum": ["epub", "mobi", "pdf", "txt"],
                    "description": "希望的格式，默认 epub"
                }
            },
            "required": ["title"]
        }
    },
    {
        "name": "play_book",
        "description": "在新窗口播放已下载的书籍，调用 lue TTS 朗读",
        "input_schema": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "书籍的 Windows 绝对路径，如 E:\\listenBookAgent\\books\\三体.epub"}
            },
            "required": ["file_path"]
        }
    },
    {
        "name": "index_book",
        "description": "为本地书籍建立 RAG 向量索引，支持 epub/txt/md，建立后才能用 ask_book 提问",
        "input_schema": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "书籍的 Windows 绝对路径"}
            },
            "required": ["file_path"]
        }
    },
    {
        "name": "ask_book",
        "description": "向已索引的书籍提问，召回相关段落后回答",
        "input_schema": {
            "type": "object",
            "properties": {
                "book_name": {"type": "string", "description": "书名（模糊匹配），如 '三体'"},
                "question":  {"type": "string", "description": "要问的问题"},
                "top_k":     {"type": "integer", "description": "召回段落数，默认 5", "default": 5}
            },
            "required": ["book_name", "question"]
        }
    },
    {
        "name": "task",
        "description": "派发搜索+下载任务给子 Agent。每本书一个 task，多个 task 同时发出即可并发执行",
        "input_schema": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string", "description": "书名，子 Agent 会自行搜索并下载最合适的版本"}
            },
            "required": ["prompt"]
        }
    }
]

# 子 Agent 的工具定义（search + download，不能再派生子任务）
SUBAGENT_TOOLS = [
    {
        "name": "search_book",
        "description": "搜索书籍，优先 Z-Library，备用鸠摩搜书。返回包含 download_url 的结果列表",
        "input_schema": {
            "type": "object",
            "properties": {
                "title":  {"type": "string", "description": "书名，可加作者名提高精度"},
                "format": {"type": "string", "enum": ["epub", "mobi", "pdf", "txt"], "description": "希望的格式，默认 epub"}
            },
            "required": ["title"]
        }
    },
    {
        "name": "download_file",
        "description": "下载书籍文件到本地 books/ 目录",
        "input_schema": {
            "type": "object",
            "properties": {
                "download_url": {"type": "string", "description": "直接下载链接"},
                "title":        {"type": "string", "description": "书名，用于生成文件名"},
                "format":       {"type": "string", "description": "文件格式，如 epub、mobi"}
            },
            "required": ["download_url", "title", "format"]
        }
    }
]


# ── 工具实现 ──
import sys
sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
from tools.jiuemo import search as jiuemo_search
from tools.zlibrary import search as zlib_search
from tools.downloader import download as do_download
from tools.player import play as do_play
from tools.rag import index_book as do_index, ask_book as do_ask
from tools import browser as _zlib_browser

BOOKS_DIR = __import__("pathlib").Path(__file__).parent / "books"

def check_local(title: str) -> str:
    """模糊匹配本地 books/ 目录"""
    if not BOOKS_DIR.exists():
        return "本地书库为空"
    matches = [f for f in BOOKS_DIR.iterdir() if title.lower() in f.name.lower()]
    if not matches:
        return f"本地未找到《{title}》相关文件"
    lines = [f"本地找到 {len(matches)} 个匹配文件："]
    for f in matches:
        lines.append(f"  {f.name}  →  {f}")
    return "\n".join(lines)


def search_book(title: str, format: str = "") -> str:
    print(f"\033[33m[search_book] 搜索: {title} ({format or '不限格式'})\033[0m")

    results = zlib_search(title, fmt=format)
    source_name = "Z-Library"

    if not results:
        print(f"\033[33m[search_book] Z-Library 无结果，转鸠摩搜书...\033[0m")
        results = jiuemo_search(title, fmt=format)
        source_name = "鸠摩搜书"

    if not results:
        return f"未找到《{title}》的电子书"

    lines = [f"[{source_name}] 找到 {len(results)} 个结果："]
    for i, r in enumerate(results, 1):
        fmt_str = r.get("format", "unknown")
        size_str = f" {r['size']}" if r.get("size") else ""
        author_str = r.get("author") or r.get("source", "")
        dl_url = r.get("download_url", r.get("url", ""))
        lines.append(f"  {i}. {r['title']} [{fmt_str}]{size_str} - {author_str}")
        lines.append(f"     download_url: {dl_url}")
    return "\n".join(lines)


def play_book(file_path: str) -> str:
    print(f"\033[33m[play_book] 播放: {file_path}\033[0m")
    result = do_play(file_path)
    return result["message"]


def download_file(download_url: str, title: str, format: str) -> str:
    print(f"\033[33m[download_file] 下载: {title}.{format}\033[0m")
    result = do_download(download_url, title, format)
    if result["success"]:
        return f"下载成功！文件保存在: {result['path']}"
    return f"下载失败: {result['error']}"


# ── s04 Subagent：全新 messages=[]，只返回摘要给父 Agent ──
SUBAGENT_HANDLERS = {
    "search_book":   lambda **kw: search_book(kw["title"], kw.get("format", "epub")),
    "download_file": lambda **kw: download_file(kw["download_url"], kw["title"], kw["format"]),
}

def run_subagent(prompt: str) -> str:
    """
    子 Agent 核心：独立的消息历史，执行下载任务。
    父 Agent 的 messages 不会被下载过程污染，只收到最终摘要。
    """
    print(f"\033[35m[subagent] 启动，任务: {prompt[:80]}\033[0m")
    sub_messages = [{"role": "user", "content": prompt}]  # ← 全新空 context

    for _ in range(10):  # 安全上限
        response = client.messages.create(
            model=MODEL,
            system=SUBAGENT_SYSTEM,
            messages=sub_messages,
            tools=SUBAGENT_TOOLS,
            max_tokens=2000,
        )
        sub_messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason != "tool_use":
            break  # 子 Agent 完成，退出循环

        results = []
        for block in response.content:
            if block.type == "tool_use":
                handler = SUBAGENT_HANDLERS.get(block.name)
                output = handler(**block.input) if handler else f"Unknown tool: {block.name}"
                results.append({"type": "tool_result", "tool_use_id": block.id, "content": str(output)})
        sub_messages.append({"role": "user", "content": results})

    # 只把最后的文字摘要返回给父 Agent，中间过程全部丢弃
    summary = "".join(b.text for b in response.content if hasattr(b, "text")) or "(无摘要)"
    print(f"\033[35m[subagent] 完成，摘要: {summary[:100]}\033[0m")
    return summary


# ── 父 Agent 工具派发表 ──
TOOL_HANDLERS = {
    "todo":          lambda **kw: TODO.update(kw["items"]),
    "check_local":   lambda **kw: check_local(kw["title"]),
    "search_book":   lambda **kw: search_book(kw["title"], kw.get("format", "epub")),
    "task":          lambda **kw: run_subagent(kw["prompt"]),
    "play_book":     lambda **kw: play_book(kw["file_path"]),
    "index_book":    lambda **kw: do_index(kw["file_path"]),
    "ask_book":      lambda **kw: do_ask(kw["book_name"], kw["question"], kw.get("top_k", 5)),
}


# ── agent_loop：s01 骨架 + s03 nag reminder + s06 上下文压缩 ──
def agent_loop(messages: list):
    rounds_since_todo = 0
    while True:
        # Layer 1：每轮都跑，静默替换旧 tool_result
        micro_compact(messages)
        # Layer 2：token 超阈值，存档并压缩
        if estimate_tokens(messages) > COMPACT_THRESHOLD:
            print("\033[33m[auto_compact] token 超限，压缩中...\033[0m")
            messages[:] = auto_compact(messages)

        response = client.messages.create(
            model=MODEL,
            system=SYSTEM,
            messages=messages,
            tools=TOOLS,
            max_tokens=4000,
        )
        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason != "tool_use":
            return

        results = []
        used_todo = False
        for block in response.content:
            if block.type != "tool_use":
                continue
            handler = TOOL_HANDLERS.get(block.name)
            output = handler(**block.input) if handler else f"Unknown tool: {block.name}"
            if block.name != "todo":
                print(f"  → {str(output)[:300]}")
            results.append({"type": "tool_result", "tool_use_id": block.id, "content": str(output)})
            if block.name == "todo":
                used_todo = True

        # s03 核心：超过3轮没更新 todo，注入提醒
        rounds_since_todo = 0 if used_todo else rounds_since_todo + 1
        if rounds_since_todo >= 3:
            results.insert(0, {"type": "text", "text": "<reminder>请用 todo 工具更新当前进度。</reminder>"})

        messages.append({"role": "user", "content": results})


if __name__ == "__main__":
    print("听书Agent")
    print("输入书名，Agent 会帮你搜索。输入 q 退出。\n")

    history = []
    while True:
        try:
            query = input("\033[36m你 >> \033[0m").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if query.lower() in ("q", "exit", ""):
            _zlib_browser.close()
            break

        history.append({"role": "user", "content": query})
        agent_loop(history)

        # 打印最后一条 assistant 消息
        last = history[-1]["content"]
        if isinstance(last, list):
            for block in last:
                if hasattr(block, "text"):
                    print(f"\n\033[32mAgent >> \033[0m{block.text}\n")
        elif isinstance(last, str):
            print(f"\n\033[32mAgent >> \033[0m{last}\n")
