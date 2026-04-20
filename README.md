github格式的readme需要md格式，这个是用仓库里的plain2txt实现的，很实用啊试一试吧
# audiobook-rag-agent

基于 KIMI API 的全流程听书 Agent。输入书名（或模糊信息如历史类书籍），自动搜索、下载电子书，TTS 朗读（支持GPT-Sovits），并支持对书籍内容进行 RAG 问答。
<img width="1642" height="921" alt="image" src="https://github.com/user-attachments/assets/9ee83b74-8b06-45ff-ac7b-0a198829498f" />
<img width="1646" height="924" alt="image" src="https://github.com/user-attachments/assets/e8ea457c-dc38-4d30-9e0c-4e7e1b53120f" />

## 功能

- **搜书**：优先从 Z-Library 搜索，备用鸠摩搜书，Playwright 自动化爬取
- **下载**：自动下载 epub/pdf 等格式到本地 `books/` 目录
- **朗读**：调用 lue + Edge TTS，在新终端窗口朗读
- **问答**：对书籍内容提问，RAG 召回相关段落后由 LLM 回答
- 例1
<img width="1922" height="999" alt="image" src="https://github.com/user-attachments/assets/acc127c0-a9db-4b9c-8f1e-4a50bd09efd2" />
<img width="1642" height="1033" alt="image" src="https://github.com/user-attachments/assets/93cdeb0e-bdb2-4542-962e-fbfe4e41b217" />
<img width="1915" height="1062" alt="image" src="https://github.com/user-attachments/assets/09fd5423-bf7a-451e-9fa5-a613143344c7" />
<img width="1903" height="1075" alt="image" src="https://github.com/user-attachments/assets/71004883-db26-42be-ad33-da79a060ed06" />
<img width="1885" height="972" alt="image" src="https://github.com/user-attachments/assets/137cd045-63d0-4f0a-819f-22816bb88121" />

- 例2
<img width="1903" height="702" alt="image" src="https://github.com/user-attachments/assets/0050dd29-a0bf-412a-ae5f-5dbd27e8caaa" />
<img width="1701" height="970" alt="image" src="https://github.com/user-attachments/assets/8e1deac0-092f-48b1-abb6-1d0cfebd9787" />
<img width="1914" height="367" alt="image" src="https://github.com/user-attachments/assets/7987c2af-c5fb-429a-83f1-c27de8e0f349" />
<img width="1921" height="1065" alt="image" src="https://github.com/user-attachments/assets/920f906f-98b4-4504-b568-5543bdcb0dee" />


## 技术栈

| 模块 | 技术 |
|------|------|
| Agent 框架 | KIMI API（ReAct 循环 + 子 Agent 上下文隔离） |
| 浏览器自动化 | Playwright（persistent context，登录态持久化） |
| 向量检索 | sentence-transformers + FAISS |
| TTS 朗读 | lue + Edge TTS（WSL Ubuntu） |

## 安装

**Windows 端**

```bash
python -m venv venv
venv\Scripts\pip install -r requirements.txt
venv\Scripts\playwright install chromium
```

**WSL 端**（朗读功能依赖）

```bash
python3 -m venv ~/lue-wslenv
~/lue-wslenv/bin/pip install lue edge-tts
```

## 配置

在 `learn-claude-code-main/.env` 中填写：

```
ANTHROPIC_BASE_URL=...
MODEL_ID=...
```

## 使用

```bash
venv\Scripts\python main.py
```

```
你 >> 帮我下载三体
你 >> 三体里面的黑暗森林法则是什么
```

## 架构说明

- **主 Agent**：负责搜书、调度、播放
- **子 Agent**：每本书独立的搜索+下载任务，上下文隔离，互不干扰
- **RAG**：epub 解析 → 500字分块 → 本地向量化 → FAISS 检索 → LLM 回答
- **上下文压缩**：超出阈值自动压缩历史对话，支持长会话


## 功能完善
- 真并行下载 — 把 browser/downloader/zlibrary 改成 async_playwright，用 asyncio.gather() 同时跑多个子 Agent
- Calibre 格式转换 — mobi 格式 lue 不支持，搜到 mobi 时自动转 epub
- 书库 JSON — 现在 check_local 只是文件名模糊匹配，缺少元数据（作者/来源/下载时间）
