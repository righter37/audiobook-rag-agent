"""
播放器 - 在新的 Windows Terminal 窗口里启动 lue
"""

import subprocess
import re
from pathlib import Path

LUE_BIN = "/home/myuser/lue-wslenv/bin/python3"


def _windows_to_wsl_path(win_path: str) -> str:
    """把 Windows 路径转成 WSL 路径，如 E:\foo\bar → /mnt/e/foo/bar"""
    p = Path(win_path)
    parts = list(p.parts)
    # 盘符 "E:\" → /mnt/e
    drive = parts[0].rstrip(":\\/").lower()
    rest = "/".join(parts[1:]).replace("\\", "/")
    return f"/mnt/{drive}/{rest}"


def play(file_path: str) -> dict:
    """
    在新 Windows Terminal 窗口里用 lue 播放书籍。
    file_path: Windows 路径，如 E:\\listenBookAgent\\books\\三体.epub
    """
    wsl_path = _windows_to_wsl_path(file_path)

    cmd = [
        "wt.exe", "wsl", "-d", "Ubuntu-22.04", "--",
        "env",
        "-u", "http_proxy", "-u", "https_proxy",
        "-u", "HTTP_PROXY", "-u", "HTTPS_PROXY",
        "-u", "ALL_PROXY", "-u", "all_proxy",
        LUE_BIN, "-m", "lue", wsl_path
    ]

    try:
        subprocess.Popen(cmd)
        return {
            "success": True,
            "message": f"已在新窗口打开，按 p 开始朗读，按 q 退出",
            "wsl_path": wsl_path,
        }
    except FileNotFoundError:
        return {
            "success": False,
            "message": "找不到 wt.exe，请确认已安装 Windows Terminal",
        }
    except Exception as e:
        return {"success": False, "message": str(e)}


if __name__ == "__main__":
    import sys
    path = sys.argv[1] if len(sys.argv) > 1 else r"E:\listenBookAgent\books\三体全集（带插图版）.epub"
    print(play(path))
