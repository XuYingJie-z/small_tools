"""查找含 tmp/<会话 ID> 的项目，或按本机 Codex 会话记录清理单个项目（Python 3.11+，Linux）。"""

import argparse
from contextlib import closing
import os
from pathlib import Path
import re
import shutil
import sqlite3
import sys
import tomllib


UUID = re.compile(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}")
ROLLOUT = re.compile(rf"rollout-.+-({UUID.pattern})\.jsonl(?:\.zst)?")


def raise_walk_error(error):
    raise error


def list_projects(root):
    root = root.expanduser().resolve(strict=True)
    projects = []
    errors = []
    for current, dirs, _ in os.walk(root, followlinks=False, onerror=errors.append):
        directory = Path(current)
        if directory.name != "tmp" or directory == root:
            continue
        if any(UUID.fullmatch(name) and not (directory / name).is_symlink() for name in dirs):
            projects.append(str(directory.parent))
    for project in sorted(projects):
        print(project)
    for error in errors:
        print(error, file=sys.stderr)
    if errors:
        sys.exit(1)


def missing_threads(candidates):
    home = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex").resolve(strict=True)
    try:
        with (home / "config.toml").open("rb") as config_file:
            config = tomllib.load(config_file)
    except FileNotFoundError:
        config = {}
    if config.get("experimental_thread_store", {}).get("type", "local") != "local":
        raise ValueError("需要使用本地 Codex 会话存储")
    db_dir = Path(config.get("sqlite_home") or os.environ.get("CODEX_SQLITE_HOME") or home)

    # 使用当前版本的索引。版本变化时防止读到升级后遗留的旧库。
    versions = [
        int(match[1])
        for path in db_dir.iterdir()
        if (match := re.fullmatch(r"state_(\d+)\.sqlite", path.name))
    ]
    if max(versions, default=None) != 5:
        raise ValueError(f"无法确认当前 Codex 会话索引为 {db_dir / 'state_5.sqlite'}")
    db_path = (db_dir / "state_5.sqlite").resolve(strict=True)
    with closing(sqlite3.connect(db_path.as_uri() + "?mode=ro", uri=True)) as db:
        if db.execute("SELECT status FROM backfill_state WHERE id = 1").fetchone() != ("complete",):
            raise ValueError("Codex 会话索引尚未完成初始化")
        # ID 全局唯一，保留归档会话以及从项目子目录启动的会话。
        missing = candidates.difference(tid for (tid,) in db.execute("SELECT id FROM threads"))

    # 兼容仍以 rollout 文件保存、尚未进入索引的会话，仅读取文件名。
    for folder in (home / "sessions", home / "archived_sessions"):
        if not missing:
            break
        try:
            folder.stat()
        except FileNotFoundError:
            continue
        for _, _, files in os.walk(folder, onerror=raise_walk_error):
            for name in files:
                match = ROLLOUT.fullmatch(name)
                if match:
                    missing.discard(match[1])
    return missing


def clean(project, delete):
    project = project.expanduser().resolve(strict=True)
    tmp = project / "tmp"
    try:
        tmp_fd = os.open(tmp, os.O_DIRECTORY | os.O_NOFOLLOW)
    except FileNotFoundError:
        print(f"没有临时目录 {tmp}")
        return
    try:
        with os.scandir(tmp_fd) as entries:
            candidates = {
                e.name
                for e in entries
                if UUID.fullmatch(e.name) and e.is_dir(follow_symlinks=False)
            }
        to_check = candidates - {os.environ.get("CODEX_THREAD_ID")}
        missing = missing_threads(to_check) if to_check else set()
        for tid in sorted(missing):
            if delete:
                shutil.rmtree(tid, dir_fd=tmp_fd)
            print("已删除" if delete else "待删除", tmp / tid)
        print(
            f"会话目录 {len(candidates)} 个，保留 {len(candidates) - len(missing)} 个，"
            f"{'已删除' if delete else '待删除'} {len(missing)} 个。"
        )
    finally:
        os.close(tmp_fd)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("project", type=Path, nargs="?", help="要预览或清理的项目根目录")
    mode.add_argument(
        "--list-projects",
        type=Path,
        metavar="<path>",
        help="递归列出 <path> 中含有 tmp/<会话 UUID>/ 的项目，每行一个绝对路径",
    )
    parser.add_argument("--delete", action="store_true", help="执行删除（默认仅预览）")
    args = parser.parse_args()
    if args.list_projects and args.delete:
        parser.error("--delete 只能用于清理单个项目")
    try:
        if args.list_projects:
            list_projects(args.list_projects)
        else:
            clean(args.project, args.delete)
    except (OSError, sqlite3.Error, ValueError) as error:
        sys.exit(f"操作已中止：{error}")
