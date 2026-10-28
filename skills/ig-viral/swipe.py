#!/usr/bin/env python3
"""
swipe.py - 集めたリールを、そのアカウントのふだんの再生数の何倍だったか
（伸び倍率）で並べ、それぞれのフックの型の名前を当てて、伸びた型のメモを
書く。日本語版。

この道具の言いたいことは1つ。再生数そのものは証拠にならない。フォロワー
200万人のアカウントの40万回は、静かな1日。フォロワー4,000人のアカウントの
40万回は、何かを見つけた。ここではアカウント自身のふだんの再生数に対する
倍率で並べる。これが「バズった」の中で、まねできる物を教えてくれる唯一の形。

入力は、見ながら埋めるタブ区切りのファイル。1行に1本、1行目に列の名前。

    account   followers   median   views    hook
    @someone  4.8万       1.1万    41.2万   誰も言わないけど最初の30本は伸びない

列の名前は日本語でもいい（アカウント・フォロワー・中央値・再生数・フック）。
数は画面の表示のまま書いていい: 「1.2万」「120万」「1.1億」「3,400」「12K」「1.2M」。
median（ふだんの再生数＝最近12本の真ん中の値）のほうが良い基準。followers しか
なければ median を空けておくと、そう表示する。hook はリールの1行目（話した言葉か
最初のテロップ）を、その人の言葉のまま。

使い方
  python3 swipe.py captured.tsv
  python3 swipe.py captured.tsv --out ~/.claude/instagram/swipe.md
  python3 swipe.py captured.tsv --json
"""

import argparse
import json
import os
import re
import statistics
import sys
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
HOOKS = os.path.join(HERE, "..", "ig-reel", "hooks.json")

try:                                              # 入っていればフックの点数も出す
    sys.path.insert(0, os.path.join(HERE, "..", "ig-reel"))
    from hookscore import run as score_hook       # noqa: E402
except Exception:                                 # ig-viral だけを写した時
    score_hook = None

COLUMN_NAMES = {
    "account": "account", "アカウント": "account", "アカウント名": "account",
    "followers": "followers", "フォロワー": "followers", "フォロワー数": "followers",
    "median": "median", "中央値": "median", "ふだん": "median", "ふだんの再生数": "median",
    "views": "views", "再生数": "views", "再生": "views", "再生回数": "views",
    "hook": "hook", "フック": "hook", "1行目": "hook",
}
UNITS = {"万": 10_000, "億": 100_000_000, "千": 1_000, "k": 1_000, "m": 1_000_000}


def parse_count(cell):
    """'1.2万' -> 12000、'41.2万' -> 412000、'1.1億'、'3,400'、'12K'、'1.2M' を数に。"""
    if not cell:
        return None
    t = unicodedata.normalize("NFKC", str(cell)).strip().lower()
    t = t.replace(",", "").replace("回", "").replace("人", "").replace("再生", "").strip()
    m = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)\s*(万|億|千|k|m)?", t)
    if not m:
        digits = re.sub(r"[^\d]", "", t)
        return int(digits) if digits else None
    value = float(m.group(1)) * UNITS.get(m.group(2) or "", 1)
    return int(round(value))


def load_formulas(path):
    try:
        d = json.load(open(path, encoding="utf-8"))
    except Exception:
        return None
    by_id = {h["id"]: h for h in d["hooks"]}
    order = d.get("classify_order") or sorted(by_id)
    return [(by_id[i]["id"], by_id[i]["name"], re.compile(by_id[i]["match"], re.IGNORECASE))
            for i in order if i in by_id]


def classify(hook, formulas):
    if not formulas:
        return None, "型なし"
    for fid, name, pattern in formulas:
        if pattern.search(hook):
            return fid, name
    return None, "型なし"


def read_rows(path):
    raw = sys.stdin.read() if path == "-" else open(path, encoding="utf-8").read()
    lines = [l for l in raw.splitlines() if l.strip() and not l.lstrip().startswith("#")]
    if not lines:
        return []
    head = [COLUMN_NAMES.get(c.strip().lower(), COLUMN_NAMES.get(c.strip(), c.strip().lower()))
            for c in lines[0].split("\t")]
    if "views" in head and "hook" in head:
        cols, body = head, lines[1:]
    else:
        cols, body = ["account", "followers", "views", "hook"], lines
    rows = []
    for line in body:
        cells = line.split("\t")
        if len(cells) < len(cols):
            cells += [""] * (len(cols) - len(cells))
        r = dict(zip(cols, [c.strip() for c in cells]))
        r["views"] = parse_count(r.get("views"))
        for k in ("followers", "median"):
            r[k] = parse_count(r.get(k))
        if r["views"] and r.get("hook"):
            rows.append(r)
    return rows


def analyse(rows, formulas):
    used_median = any(r.get("median") for r in rows)
    for r in rows:
        base = r.get("median") or r.get("followers") or 0
        r["baseline"] = base
        r["outlier"] = round(r["views"] / base, 2) if base else None
        r["formula_id"], r["formula"] = classify(r["hook"], formulas)
        r["chars"] = len(re.sub(r"\s", "", r["hook"]))
        if score_hook:
            _, overall, verdict, _ = score_hook(r["hook"])
            r["hook_score"], r["hook_verdict"] = round(overall, 1), verdict
        else:
            r["hook_score"], r["hook_verdict"] = None, None
    ranked = sorted(rows, key=lambda r: -(r["outlier"] or 0))
    third = max(1, len(ranked) // 3)
    top, bottom = ranked[:third], ranked[-third:]

    def med(items, key):
        vals = [i[key] for i in items if i.get(key) is not None]
        return round(statistics.median(vals), 1) if vals else None

    counts = {}
    for r in top:
        counts[r["formula"]] = counts.get(r["formula"], 0) + 1
    return {
        "baseline": "アカウントの中央値" if used_median else "フォロワー数",
        "n": len(ranked),
        "accounts": len({r.get("account", "") for r in ranked}),
        "reels": ranked,
        "top_formulas": sorted(counts.items(), key=lambda kv: -kv[1]),
        "top_hook_score": med(top, "hook_score"),
        "bottom_hook_score": med(bottom, "hook_score"),
        "top_chars": med(top, "chars"),
        "bottom_chars": med(bottom, "chars"),
        "unclassified": sum(1 for r in ranked if r["formula"] == "型なし"),
    }


def _w(s):
    return sum(2 if unicodedata.east_asian_width(c) in "FWA" else 1 for c in s)


def _pad(s, n):
    while _w(s) > n:
        s = s[:-1]
    return s + " " * (n - _w(s))


def render(a, out=sys.stdout):
    head = (f"伸びた型のメモ  ·  {a['n']}本  ·  {a['accounts']}アカウント  ·  "
            f"基準: {a['baseline']}")
    print("\n" + head, file=out)
    print("=" * 78, file=out)
    for r in a["reels"]:
        mult = f"{r['outlier']:.1f}倍" if r["outlier"] else "   ?"
        score = f"{r['hook_score']:.0f}" if r["hook_score"] is not None else " -"
        fid = f"#{r['formula_id']:<2}" if r["formula_id"] else "-  "
        print(f"  {mult:>8}  フック{score:>3}点  {fid} {_pad(r['formula'], 22)} "
              f"{_pad(r.get('account', ''), 16)} {r['views']:>11,}回", file=out)
        print(f"            「{r['hook'][:60]}」", file=out)
    print("-" * 78, file=out)
    print("このまとまりで効いている物", file=out)
    if a["top_formulas"]:
        print("  伸び倍率の上位3分の1:  "
              + "、".join(f"{n} ×{c}" for n, c in a["top_formulas"][:4]), file=out)
    if a["top_hook_score"] is not None:
        print(f"  フックの点数（中央値）: 上位 {a['top_hook_score']:.0f}点  "
              f"／ 下位 {a['bottom_hook_score']:.0f}点", file=out)
    print(f"  フックの長さ（中央値）: 上位 {a['top_chars']}字  ／ 下位 {a['bottom_chars']}字", file=out)
    print(f"  型なし:                 {a['unclassified']} / {a['n']}本。手で読む。"
          "まだ持っていない型はそこに隠れている。", file=out)
    print("\n  手で集めたまとまりは手がかりで、証明ではない。12本では何も言えない。"
          "\n  6アカウントで40本あれば何かが言える。信じる前にもっと集める。\n", file=out)


def to_markdown(a):
    lines = ["# 伸びた型のメモ（swipe.md）", "",
             f"{a['accounts']}アカウントの{a['n']}本。{a['baseline']}に対する倍率の順。", ""]
    for r in a["reels"]:
        mult = f"{r['outlier']:.1f}倍" if r["outlier"] else "?"
        lines += [f"## {mult}  {r['formula']}  （{r.get('account', '')}）",
                  f"- 再生数: {r['views']:,}  基準: {r['baseline']:,}",
                  f"- フックの点数: {r['hook_score']}  長さ: {r['chars']}字",
                  f"- フック: 「{r['hook']}」", ""]
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser(description="集めたリールを伸び倍率で並べる（日本語版）。")
    ap.add_argument("input", nargs="?", default="-", help="タブ区切りのファイル。- で標準入力")
    ap.add_argument("--hooks", default=HOOKS, help="ig-reel/hooks.json の場所")
    ap.add_argument("--out", help="伸びた型のメモを Markdown でここにも書く")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    rows = read_rows(args.input)
    if not rows:
        print("使える行がない。少なくとも再生数とフックの列があるタブ区切りのファイルが要る。",
              file=sys.stderr)
        sys.exit(2)
    formulas = load_formulas(args.hooks)
    a = analyse(rows, formulas)
    if not formulas:
        print("注意: hooks.json が見つからず、型の名前を付けていない。--hooks で場所を渡す。",
              file=sys.stderr)
    if score_hook is None:
        print("注意: hookscore.py を読み込めず、フックの点数は出していない。", file=sys.stderr)

    if args.json:
        print(json.dumps(a, indent=2, ensure_ascii=False))
    else:
        render(a)
    if args.out:
        path = os.path.expanduser(args.out)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        open(path, "w", encoding="utf-8").write(to_markdown(a))
        print(f"書き出し: {path}", file=sys.stderr)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    main()
