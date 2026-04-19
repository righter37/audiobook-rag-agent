# 听书 Agent — Claude 上下文

## 项目目标

用户输入书名 → Agent 自动搜索、下载、在新窗口用 lue 朗读。

## 运行环境

- **Agent 本体**：Windows Python，`venv\Scripts\python main.py`
- **lue 播放器**：WSL Ubuntu-22.04，通过 `wt.exe` 弹出新窗口运行
- **lue 安装位置**：WSL 内 `~/lue-wslenv/bin/python3 -m lue`（非 `/usr/local/bin/lue`，后者用系统 Python，没有 edge-tts）
- **WSL 发行版**：必须指定 `-d Ubuntu-22.04`，默认 distro 是 docker-desktop（没有 bash）

## 当前实现的工具

| 工具 | 文件 | 说明 |
|------|------|------|
| `search_book` | `tools/zlibrary.py` + `tools/jiuemo.py` | Z-Library 优先，鸠摩备用，Playwright 爬虫 |
| `download_file` | `tools/downloader.py` | Playwright 带 cookie 下载到 `books/` |
| `play_book` | `tools/player.py` | `wt.exe wsl -d Ubuntu-22.04` 弹新窗口跑 lue |

## 关键技术细节

**Z-Library**
- cookie 保存在 `tools/.zlibrary_cookies.json`
- 搜索 URL 格式：`/s/{query}`（不是 `/search?q=`）
- 书籍信息在 Web Component `<z-bookcard>` 的属性里（extension/filesize/href/download）
- `download_url` 直接从搜索结果的 `download` 属性获取，无需跳详情页

**lue 播放器**
- lue 是 TUI 程序，必须在真实终端里运行，不能 subprocess 静默执行
- 通过 `wt.exe` 弹出新 Windows Terminal 窗口
- 用户需要在新窗口切换英文输入法后按 `p` 开始朗读
- 第一次播放有 5-10 秒 Edge TTS 预热延迟

**lue 支持的格式**：`.epub` `.pdf` `.txt` `.docx` `.html` `.rtf` `.md`（不支持 `.mobi`）

**Windows → WSL 路径转换**：`E:\foo\bar` → `/mnt/e/foo/bar`（见 `tools/player.py`）

## 未完成的模块（按优先级）

- [ ] 书库 JSON：记录已下载书籍，避免重复下载
- [ ] Subagent 拆分（s04）：SearchAgent / DownloadAgent 独立上下文
- [ ] 上下文压缩（s06）：长会话 token 管理
- [ ] Calibre 格式转换：仅 mobi 需要，其他格式 lue 原生支持

## 踩过的坑

1. `wsl --` 默认用 docker-desktop distro，没有 bash → 加 `-d Ubuntu-22.04`
2. `/usr/local/bin/lue` shebang 是 `#!/usr/bin/python3`（系统 Python），没有 edge-tts → 改用 `~/lue-wslenv/bin/python3 -m lue`
3. `bash -l -c` 会加载 conda 环境，干扰运行 → 直接指定完整 python 路径
4. lue 界面键盘无响应 → 中文输入法拦截，需切英文输入（Shift）
5. Z-Library 搜索用 `data-href` 不是 `href`，书名在 slot 子元素里
