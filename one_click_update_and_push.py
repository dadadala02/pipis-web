#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import datetime as dt
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
UPDATE_MD_SCRIPT = ROOT / "一鍵自動填台股自選股.py"
MARKDOWN_FILE = ROOT / "台股自選股_AI報告模板.md"
REPORT_MD_FILE = ROOT / "report.md"
INDEX_FILE = ROOT / "index.html"


def run_cmd(args, cwd=ROOT, check=True):
    return subprocess.run(args, cwd=str(cwd), text=True, check=check)


def escape_js_template_literal(text: str) -> str:
    # Keep markdown safe inside JS template literal.
    return (
        text.replace("\\", "\\\\")
        .replace("`", "\\`")
        .replace("${", "\\${")
    )


def update_markdown_file() -> None:
    if not UPDATE_MD_SCRIPT.exists():
        raise FileNotFoundError(f"找不到腳本：{UPDATE_MD_SCRIPT.name}")

    print("[1/4] 更新台股報告 Markdown...")
    run_cmd([sys.executable, str(UPDATE_MD_SCRIPT), "--copy"])


def sync_markdown_to_report_md() -> bool:
    if not MARKDOWN_FILE.exists():
        raise FileNotFoundError(f"找不到報告檔：{MARKDOWN_FILE.name}")

    print("[2/4] 將最新報告寫入 report.md...")
    markdown_text = MARKDOWN_FILE.read_text(encoding="utf-8")

    changed = True
    if REPORT_MD_FILE.exists():
        changed = REPORT_MD_FILE.read_text(encoding="utf-8") != markdown_text

    if changed:
        REPORT_MD_FILE.write_text(markdown_text, encoding="utf-8")
        print("    已更新 report.md")
    else:
        print("    report.md 內容無變更")
    return changed


def sync_markdown_to_index() -> bool:
    if not MARKDOWN_FILE.exists():
        raise FileNotFoundError(f"找不到報告檔：{MARKDOWN_FILE.name}")
    if not INDEX_FILE.exists():
        raise FileNotFoundError(f"找不到首頁：{INDEX_FILE.name}")

    print("[2/4] 將最新報告同步到 index.html 預設備援內容...")
    markdown_text = MARKDOWN_FILE.read_text(encoding="utf-8")
    escaped = escape_js_template_literal(markdown_text)
    index_text = INDEX_FILE.read_text(encoding="utf-8")

    pattern = r"const defaultMarkdownText = `.*?`;"
    replacement = f"const defaultMarkdownText = `{escaped}`;"
    new_text, count = re.subn(pattern, replacement, index_text, count=1, flags=re.DOTALL)

    if count != 1:
        raise RuntimeError("找不到 defaultMarkdownText 區塊，無法自動更新 index.html")

    changed = new_text != index_text
    if changed:
        INDEX_FILE.write_text(new_text, encoding="utf-8")
        print("    已更新 index.html")
    else:
        print("    index.html 內容無變更")
    return changed


def git_repo_ready() -> bool:
    try:
        run_cmd(["git", "rev-parse", "--is-inside-work-tree"])
        return True
    except Exception:
        return False


def push_to_github() -> None:
    print("[3/4] 準備提交並上傳到 GitHub...")
    if not git_repo_ready():
        print("    目前資料夾尚未初始化 Git，已略過上傳。")
        print("    請先在此資料夾執行一次：")
        print("    git init")
        print("    git remote add origin <你的GitHub倉庫URL>")
        print("    git branch -M main")
        return

    # 提交 report.md 與 index.html
    run_cmd(["git", "add", "report.md", "index.html"])

    staged_diff = subprocess.run(
        ["git", "diff", "--cached", "--quiet"],
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        check=False,
    )
    if staged_diff.returncode == 0:
        print("    index.html 無變更，略過 commit / push")
        return

    commit_msg = f"chore: 一鍵更新台股網站 {dt.datetime.now().strftime('%Y-%m-%d %H:%M')}"
    run_cmd(["git", "commit", "-m", commit_msg])

    branch = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip() or "main"

    run_cmd(["git", "push", "origin", branch])
    print(f"    已推送到 origin/{branch}")


def main() -> int:
    try:
        update_markdown_file()
        sync_markdown_to_report_md()
        push_to_github()
        print("[4/4] 完成：網站內容已更新。")
        return 0
    except subprocess.CalledProcessError as err:
        print(f"\n執行失敗：{err}")
        return 1
    except Exception as err:
        print(f"\n發生錯誤：{err}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
