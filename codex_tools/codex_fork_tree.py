#!/usr/bin/env python3
"""展示 Codex 会话的 fork 树，或按从叶到根的顺序删除指定分支。"""

import argparse
import json
import os
import sqlite3
import subprocess
import sys
from collections import defaultdict
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def open_rollout(path):
    if path.suffix != ".zst":
        with path.open(encoding="utf-8") as stream:
            yield stream
        return

    try:
        decoder = subprocess.Popen(["zstd", "-qdc", "--", path],
                                   stdout=subprocess.PIPE, encoding="utf-8")
    except FileNotFoundError:
        sys.exit("读取 .jsonl.zst 会话需要在 PATH 中安装 zstd。")
    # 提前找到元数据或首条提问时，先关闭管道，再等待解压进程退出。
    with decoder, decoder.stdout as stream:
        yield stream


def first_meta(path):
    try:
        with open_rollout(path) as f:
            for _ in range(10):
                line = f.readline()
                if not line:
                    break
                record = json.loads(line)
                if record.get("type") == "session_meta":
                    return record.get("payload", {})
    except (OSError, ValueError):
        pass
    return None


def first_user_prompt(path):
    try:
        with open_rollout(path) as f:
            for line in f:
                try:
                    item = json.loads(line)
                except ValueError:
                    continue
                p = item.get("payload", {})
                if item.get("type") == "event_msg" and p.get("type") == "user_message":
                    return p.get("message", "")
                if (
                    item.get("type") == "response_item"
                    and p.get("type") == "message"
                    and p.get("role") == "user"
                ):
                    for part in p.get("content", []):
                        if part.get("type") in ("input_text", "text") and part.get("text"):
                            return part["text"]
    except OSError:
        pass
    return ""


def short(s, limit=72):
    s = " ".join(str(s).split())
    return s if len(s) <= limit else s[: limit - 1] + "…"


def delete_subtree(target, children, label, apply):
    order = []
    visited = set()

    def visit(tid):
        if tid in visited:
            sys.exit(f"fork 关系存在循环，无法生成删除顺序：{tid}")
        visited.add(tid)
        for child in children.get(tid, []):
            visit(child)
        order.append(tid)

    visit(target)
    print(f"当前树中待删除的会话（共 {len(order)} 个，按执行顺序）：")
    for index, tid in enumerate(order, 1):
        print(f"{index}. {tid}  [{label(tid)}]")
    if not apply:
        print("本次仅预览。确认后在同一命令末尾加 --apply 执行。")
        return

    for index, tid in enumerate(order, 1):
        print(f"[{index}/{len(order)}] 正在删除 {tid}", flush=True)
        try:
            subprocess.run(["codex", "delete", "--force", "--", tid], check=True)
        except (OSError, subprocess.CalledProcessError) as error:
            sys.exit(f"已停止，前 {index - 1} 个删除成功。失败节点 {tid}：{error}")
        print(f"已删除 {tid}", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", metavar="SESSION_ID", help="目标会话的 UUID")
    parser.add_argument("--delete-tree", action="store_true", help="预览当前树中此节点及其后代的删除顺序")
    parser.add_argument("--apply", action="store_true", help="执行 --delete-tree 列出的删除")
    args = parser.parse_args()
    if args.apply and not args.delete_tree:
        parser.error("--apply 需要与 --delete-tree 一起使用")
    target = args.target
    home = Path(os.environ.get("CODEX_HOME", "~/.codex")).expanduser().resolve()
    nodes = {}

    for dirname in ("sessions", "archived_sessions"):
        folder = home / dirname
        if not folder.exists():
            continue
        for path in folder.rglob("*.jsonl*"):
            if not path.name.endswith((".jsonl", ".jsonl.zst")):
                continue
            meta = first_meta(path)
            if not meta or not meta.get("id"):
                if path.name.startswith("rollout-"):
                    print(f"未读到会话元数据，已跳过 {path}", file=sys.stderr)
                continue
            tid = str(meta["id"])
            try:
                mtime = path.stat().st_mtime
            except OSError:
                continue
            if tid not in nodes or mtime > nodes[tid]["mtime"]:
                nodes[tid] = {"meta": meta, "path": path, "mtime": mtime}

    if target not in nodes:
        sys.exit(f"未找到 Session: {target}\n已扫描 {len(nodes)} 个会话；目录: {home}")

    # Explicit names set by /rename, with the latest nonempty entry winning.
    index_names = {}
    index_file = home / "session_index.jsonl"
    if index_file.exists():
        with index_file.open(encoding="utf-8") as f:
            for line in f:
                try:
                    entry = json.loads(line)
                    tid = str(entry.get("id", ""))
                    name = entry.get("thread_name", "")
                    if isinstance(name, str) and name.strip():
                        index_names[tid] = name.strip()
                except ValueError:
                    continue

    # Optional fallback: names/titles maintained by newer Codex versions.
    db_names, db_titles = {}, {}
    db_files = sorted(home.glob("state_*.sqlite"), key=lambda p: p.stat().st_mtime, reverse=True)
    for db_path in db_files:
        try:
            with sqlite3.connect(db_path.as_uri() + "?mode=ro", uri=True, timeout=1) as conn:
                columns = {row[1] for row in conn.execute("PRAGMA table_info(threads)")}
                fields = [col for col in ("id", "name", "title") if col in columns]
                if "id" not in fields:
                    continue
                for values in conn.execute(f"SELECT {', '.join(fields)} FROM threads"):
                    row = dict(zip(fields, values))
                    tid = str(row["id"])
                    if row.get("name"):
                        db_names.setdefault(tid, row["name"])
                    if row.get("title"):
                        db_titles.setdefault(tid, row["title"])
        except (OSError, sqlite3.Error):
            continue

    def label(tid):
        meta = nodes[tid]["meta"]
        name = (
            index_names.get(tid) or db_names.get(tid) or meta.get("thread_name") or meta.get("name")
        )
        if name:
            return short(name)
        if db_titles.get(tid):
            return short(db_titles[tid])
        preview = first_user_prompt(nodes[tid]["path"])
        return "首条提问: " + short(preview, 60) if preview else "未命名"

    children = defaultdict(list)
    for tid, node in nodes.items():
        parent = node["meta"].get("forked_from_id")
        if parent and parent != tid:
            children[str(parent)].append(tid)
    for kids in children.values():
        kids.sort(key=lambda tid: (nodes[tid]["meta"].get("timestamp", ""), tid))

    if args.delete_tree:
        delete_subtree(target, children, label, args.apply)
        return

    root = target
    ancestors = set()
    while root not in ancestors:
        ancestors.add(root)
        parent = nodes[root]["meta"].get("forked_from_id")
        if not parent or str(parent) not in nodes:
            break
        root = str(parent)

    printed = set()

    def show(tid, prefix="", last=True, is_root=False):
        if tid in printed:
            return
        printed.add(tid)
        branch = "" if is_root else ("└── " if last else "├── ")
        mark = "  <-- TARGET" if tid == target else ""
        print(f"{prefix}{branch}{tid}  [{label(tid)}]{mark}")
        child_prefix = prefix if is_root else prefix + ("    " if last else "│   ")
        kids = children.get(tid, [])
        for i, child in enumerate(kids):
            show(child, child_prefix, i == len(kids) - 1)

    show(root, is_root=True)


if __name__ == "__main__":
    main()
