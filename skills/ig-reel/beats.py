#!/usr/bin/env python3
"""
beats.py - リールの台本を、撮る前に秒割り表にする。日本語版。

1行ずつ、言うのに何秒かかるかを見積もって時刻に積み上げ、編集でリールを
殺す4つを知らせる。3秒を過ぎるフック、見ている人が離れるほど長い1カット、
具体的な物が何もない行の連続、言っていた長さとの差。

秒数は「読みの長さ（かなに直した音の数）÷ 1秒に話すかなの数」の見積もり。
編集の計画には十分で、録音の代わりにはならない。初期値は1秒に9かな。
日本語のリール8本（カット編集後）で測ると中央値は1秒に約10かなだった。
自分の速さは、台本を声に出して読んだ秒数を --measured に入れると出る。
その数を --cps に入れて使う。

使い方
  python3 beats.py script.txt
  python3 beats.py script.txt --target 30
  python3 beats.py script.txt --cps 10 --target 45
  python3 beats.py script.txt --measured 42     # 読んだら42秒だった → 自分の速さが出る
  python3 beats.py script.txt --json
"""

import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import jp  # noqa: E402

DEFAULT_CPS = 9.0
HOOK_WINDOW = 3.0        # 秒。ここを過ぎたら、指はもう決めている。
MAX_BEAT = 4.0           # 秒。画面が変わらないまま1つの話をしていい長さ。
ABSTRACT_RUN = 3         # 確かめられる物が何もない行が、これだけ続いたら知らせる。


def tc(seconds):
    m, s = divmod(seconds, 60)
    return f"{int(m)}:{s:04.1f}"


def split_beats(raw, cps):
    """1行を1カットとして扱う。ただし1カットにしては長すぎる行は文で切る。"""
    beats = []
    for line in [l.strip() for l in raw.splitlines()]:
        if not line:
            continue
        if jp.yomi(line) / cps <= MAX_BEAT * 1.5:
            beats.append(line)
            continue
        # 長い段落: 句点で切って、秒数が意味を持つようにする。
        parts = [p.strip() for p in re.split(r"(?<=[。！？!?])", line) if p.strip()]
        buf = ""
        for part in parts:
            candidate = buf + part
            if buf and jp.yomi(candidate) / cps > MAX_BEAT:
                beats.append(buf)
                buf = part
            else:
                buf = candidate
        if buf:
            beats.append(buf)
    return beats


def analyse(raw, cps=DEFAULT_CPS, target=None):
    beats = split_beats(raw, cps)
    if not beats:
        return None

    rows, clock = [], 0.0
    for i, text in enumerate(beats):
        mora = jp.yomi(text)
        dur = mora / cps
        rows.append({
            "n": i + 1,
            "start": round(clock, 2),
            "dur": round(dur, 2),
            "mora": round(mora),
            "chars": len(re.sub(r"\s", "", text)),
            "text": text,
            "concrete": len(jp.concrete(text)),
            "label": "",
            "flags": [],
        })
        clock += dur
    total = clock

    # リールの骨組みの位置に札を付ける。
    for r in rows:
        if r["n"] == 1 or r["start"] + r["dur"] <= HOOK_WINDOW:
            r["label"] = "フック"
    rows[-1]["label"] = "締め" if rows[-1]["label"] != "フック" else "フック/締め"
    half = total / 2
    for r in rows:
        if not r["label"] and r["start"] <= half < r["start"] + r["dur"]:
            r["label"] = "真ん中"

    notes = []
    if rows[0]["dur"] > HOOK_WINDOW:
        rows[0]["flags"].append(f"フックが{rows[0]['dur']:.1f}秒。{HOOK_WINDOW:.0f}秒を過ぎている")
        notes.append(f"1行目を言うのに{rows[0]['dur']:.1f}秒かかる。約{int(HOOK_WINDOW * cps)}字"
                     "（読みの音の数）以内に削らないと、"
                     "見るかどうか決まった後にフックが届く。")
    if rows[0]["concrete"] == 0:
        notes.append("1行目に数字も名前もない。確かめられる物のないフックは、流される。")

    for r in rows:
        if r["dur"] > MAX_BEAT:
            r["flags"].append(f"1カットに{r['dur']:.1f}秒")
    long_beats = [r["n"] for r in rows if r["dur"] > MAX_BEAT]
    if long_beats:
        notes.append(f"{', '.join(map(str, long_beats))}行目が{MAX_BEAT:.0f}秒を超える。"
                     "行を分けるか、その行の途中で画面を変える。止まった画面で人は離れる。")

    run, start = 0, None
    for r in rows:
        if r["concrete"] == 0:
            run += 1
            start = start if start is not None else r["n"]
            if run == ABSTRACT_RUN:
                notes.append(f"{start}〜{r['n']}行目に具体的な物が何もない。"
                             "どれか1行に数字・名前・値段を入れる。")
        else:
            run, start = 0, None

    # 最後の行が、最初の行に戻してくれるか。
    loop = sorted(jp.content_tokens(rows[0]["text"]) & jp.content_tokens(rows[-1]["text"]))
    if loop:
        notes.append(f"ループあり: 最後の行がフックの「{'、'.join(loop[:3])}」をもう一度言っている。"
                     "2回目の再生はタダのリーチ。")
    else:
        notes.append("ループなし。最後の行がフックと同じ言葉を1つも持っていないので、平らに終わる。"
                     "1行目の言葉を1つ繰り返すのが、いちばん安い2回目の再生。")

    if target:
        delta = total - target
        if abs(delta) <= target * 0.1:
            notes.append(f"長さは狙いどおり（{total:.1f}秒／狙い{target:g}秒）。")
        elif delta > 0:
            notes.append(f"狙いより{delta:.1f}秒長い。約{int(delta * cps)}字削る。")
        else:
            notes.append(f"狙いより{-delta:.1f}秒短い。約{int(-delta * cps)}字足すか、"
                         "短いまま撮る。たいてい短いほうが正しい。")

    return {
        "cps": cps, "target": target,
        "total_seconds": round(total, 2),
        "total_chars": sum(r["chars"] for r in rows),
        "total_mora": round(sum(r["mora"] for r in rows)),
        "beats": rows,
        "notes": notes,
    }


def pad(s, n):
    return s + " " * max(0, n - jp.width(s))


def render(a, out=sys.stdout):
    head = (f"秒割り表  ·  {a['total_chars']}字（読み約{a['total_mora']}音）  ·  "
            f"約{a['total_seconds']:.1f}秒（1秒に{a['cps']:g}かな）"
            + (f"  ·  狙い{a['target']:g}秒" if a["target"] else ""))
    print("\n" + head, file=out)
    print("=" * 72, file=out)
    for r in a["beats"]:
        label = pad(r["label"], 11) if r["label"] else " " * 11
        print(f"  {tc(r['start'])}  {r['dur']:4.1f}秒  {label}{r['text']}", file=out)
        for f in r["flags"]:
            print(f"  {'':>6}  {'':>6}  {'':<11}^ {f}", file=out)
    print("-" * 72, file=out)
    for n in a["notes"]:
        print(f"  - {n}", file=out)
    print("", file=out)


def main():
    ap = argparse.ArgumentParser(description="リールの台本を秒割り表にする（日本語版）。")
    ap.add_argument("input", nargs="?", default="-", help="台本のファイル。- で標準入力")
    ap.add_argument("--cps", type=float, default=DEFAULT_CPS,
                    help=f"1秒に話すかなの数（初期値 {DEFAULT_CPS}）")
    ap.add_argument("--target", type=float, help="狙いの長さ（秒）")
    ap.add_argument("--measured", type=float,
                    help="台本を声に出して読んだ実際の秒数。自分の速さ（--cps の値）を出す")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    raw = sys.stdin.read() if args.input == "-" else open(args.input, encoding="utf-8").read()
    if args.measured:
        mora = sum(jp.yomi(l) for l in raw.splitlines() if l.strip())
        cps = mora / args.measured
        print(f"読みの長さ 約{mora:.0f}音 ÷ {args.measured:g}秒 = 1秒に約{cps:.1f}かな。"
              f"\n次から --cps {cps:.1f} を付ける（voice.md の「話す速さ」にも書いておく）。")
        args.cps = cps
    a = analyse(raw, cps=args.cps, target=args.target)
    if not a:
        print("台本が空", file=sys.stderr)
        sys.exit(2)
    if args.json:
        print(json.dumps(a, indent=2, ensure_ascii=False))
    else:
        render(a)
    sys.exit(0)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    main()
