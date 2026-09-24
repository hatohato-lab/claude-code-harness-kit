#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Claude Code の生ログを読み、セッションの情報と発言を時刻つきで出す道具です。

生ログは、作業フォルダごとに次の場所へ1セッション1ファイルで残っています。
  ~/.claude/projects/<作業フォルダのパスの、英数字以外を - にした名前>/<セッションID>.jsonl

使い方（作業フォルダで実行します）:
  python session_log.py all                     直近12時間に更新のあった全セッションの情報
  python session_log.py info <セッションID>        1つのセッションの情報
  python session_log.py msgs <セッションID>        そのセッションの今日の発言（時刻つき）
  python session_log.py msgs <セッションID> 2026-09-23   指定した日の発言
  python session_log.py msgs <セッションID> all    全期間の発言（日付つき）

Windows と Linux の両方で動きます。読むだけで、ファイルは書きません。
"""
import datetime as dt
import json
import os
import re
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


def projects_root() -> Path:
    base = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(os.path.expanduser("~"), ".claude")
    return Path(base) / "projects"


def project_dir() -> Path:
    """いまの作業フォルダに対応する生ログのフォルダを返します（大文字と小文字は区別しません）。"""
    want = re.sub(r"[^A-Za-z0-9]", "-", os.getcwd()).lower()
    root = projects_root()
    if root.is_dir():
        for d in root.iterdir():
            if d.is_dir() and d.name.lower() == want:
                return d
    sys.exit(f"生ログのフォルダが見つかりません: {root / want}\n作業フォルダ（Claude Code を開いたフォルダ）で実行してください。")


def to_local(ts: str) -> dt.datetime:
    return dt.datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone()


def scan(path: Path) -> dict:
    """名前、開始と最終更新、圧縮回数、行数、モデル、今日の発言数を数えます。"""
    name, first, last, model = "", "", "", ""
    compacts = lines = today_msgs = 0
    today = dt.date.today()
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            lines += 1
            m = re.search(r'"customTitle":"([^"]+)"', line)
            if m:
                name = m.group(1)
            if '"subtype":"compact_boundary"' in line:
                compacts += 1
            m = re.search(r'"model":"(claude-[^"]+)"', line)
            if m:
                model = m.group(1)
            m = re.search(r'"timestamp":"([^"]+)"', line)
            if m:
                if not first:
                    first = m.group(1)
                last = m.group(1)
                if len(line) < 20000 and '"type":"user"' in line:
                    try:
                        if to_local(m.group(1)).date() == today:
                            today_msgs += 1
                    except ValueError:
                        pass
    return {
        "name": name, "first": first, "last": last, "compacts": compacts,
        "lines": lines, "model": model, "today_msgs": today_msgs,
        "mb": path.stat().st_size / 1024 / 1024,
    }


def fmt_time(ts: str, pattern: str) -> str:
    try:
        return to_local(ts).strftime(pattern)
    except ValueError:
        return "不明"


def cmd_all() -> None:
    d = project_dir()
    limit = dt.datetime.now().timestamp() - 12 * 3600
    files = [p for p in d.glob("*.jsonl") if p.stat().st_mtime > limit]
    for p in sorted(files, key=lambda x: x.stat().st_mtime, reverse=True):
        s = scan(p)
        print(f"===== {s['name'] or '（名前なし）'} =====")
        print(f"セッションID  {p.stem}")
        print(f"開始          {fmt_time(s['first'], '%m-%d %H:%M')}   最終更新  {fmt_time(s['last'], '%m-%d %H:%M')}")
        print(f"圧縮 {s['compacts']}回   {s['mb']:.1f} MB / {s['lines']:,} 行   {s['model'] or '不明'}")
        print(f"今日の発言 {s['today_msgs']}件")
        print()


def cmd_info(sid: str) -> None:
    p = project_dir() / f"{sid}.jsonl"
    if not p.is_file():
        sys.exit(f"生ログがありません: {p}")
    s = scan(p)
    print(f"名前          {s['name'] or '未設定（/rename で付ける）'}")
    print(f"セッションID  {sid}")
    print(f"生ログ        {p}")
    print(f"開始          {fmt_time(s['first'], '%Y-%m-%d %H:%M')}")
    print(f"最終更新      {fmt_time(s['last'], '%Y-%m-%d %H:%M')}")
    print(f"圧縮回数      {s['compacts']} 回")
    print(f"ログの大きさ  {s['mb']:.1f} MB / {s['lines']:,} 行")
    print(f"モデル        {s['model'] or '不明'}")


def cmd_msgs(sid: str, day: str = "today") -> None:
    p = project_dir() / f"{sid}.jsonl"
    if not p.is_file():
        sys.exit(f"生ログがありません: {p}")
    target = None if day == "all" else (dt.date.today() if day == "today" else dt.date.fromisoformat(day))
    pattern = "%m-%d %H:%M" if target is None else "%H:%M"
    with open(p, encoding="utf-8", errors="replace") as f:
        for line in f:
            if len(line) > 200000 or '"type":"user"' not in line:
                continue
            try:
                o = json.loads(line)
            except ValueError:
                continue
            if o.get("type") != "user" or not o.get("timestamp"):
                continue
            t = to_local(o["timestamp"])
            if target is not None and t.date() != target:
                continue
            c = (o.get("message") or {}).get("content")
            if isinstance(c, str):
                txt = c
            elif isinstance(c, list):
                txt = "".join(x.get("text", "") for x in c if isinstance(x, dict) and x.get("type") == "text")
            else:
                txt = ""
            txt = txt.strip()
            if not txt or re.match(r"^<(local-command|command-name|system-reminder)", txt) or txt.startswith("[Request interrupted"):
                continue
            one_line = re.sub(r"\s+", " ", txt)[:40]
            print(f"{t.strftime(pattern)}  {one_line}")


def main() -> None:
    a = sys.argv[1:]
    if a[:1] == ["all"]:
        cmd_all()
    elif len(a) == 2 and a[0] == "info":
        cmd_info(a[1])
    elif len(a) in (2, 3) and a[0] == "msgs":
        cmd_msgs(a[1], a[2] if len(a) == 3 else "today")
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
