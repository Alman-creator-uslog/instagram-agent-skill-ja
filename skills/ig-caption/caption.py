#!/usr/bin/env python3
"""
caption.py - インスタのキャプションを検査し、フィードで「…続きを読む」の前に
何が見えるかをそのまま見せる。日本語版。

英語版は「前から約125文字」で切っていた。日本語は1文字の幅が英字の約2倍で、
しかも行で切られるので、文字数では見積もれない。ここでは画面の幅（全角2・
半角1）で1行ずつ折り返し、最初の2行（1行目はユーザーネームの分だけ短い）に
入る所までを「見える部分」とする。改行を入れると、その行はそこで終わる。

見える行数・1行の幅は機種・文字の大きさ・表示する場所で変わる。初期値は
iPhone のフィードの見当（1行に全角約23字・2行）。自分のスマホで1回確かめて、
--width と --lines で合わせる。リールの画面のキャプションはもっと短い（1行ほど）。

使い方
  python3 caption.py caption.txt
  python3 caption.py caption.txt --keywords "提案書,見積もり"
  python3 caption.py caption.txt --handle your_name    # 1行目の頭に出るユーザーネーム
  python3 caption.py caption.txt --lines 1             # リールの画面で見る時
  python3 caption.py caption.txt --json
"""

import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import jp  # noqa: E402

LIMIT = 2200             # キャプションの上限（文字）。
LINE_WIDTH = 46          # 1行の幅（半角1・全角2で数える）。全角なら約23字。
LINES = 2                # 「…続きを読む」の前に見える行数。
HANDLE_WIDTH = 14        # 1行目の頭のユーザーネームの幅の見当（--handle で正確に）。
TAIL = "… 続きを読む"
HASHTAG_LIMIT = 5        # 1投稿のハッシュタグの上限。2025年12月18日から（それまでは30）。
                         # インスタの @Creators の説明: 一般的なタグをたくさん付けるより、
                         # 絞った5個までのほうが、投稿の成績にも見る人の体験にも良い。

HASHTAG_RE = re.compile(r"(?:^|(?<=[\s　]))(#[^\s#＃　、。！？!?,，.]+)")
FULLWIDTH_TAG_RE = re.compile(r"＃[^\s#＃　、。]+")
MENTION_RE = re.compile(r"(?:^|(?<=[\s　]))(@[A-Za-z0-9_.]+)")
LINK_RE = re.compile(r"https?://\S+|\bwww\.\S+|\b[a-z0-9-]+\.(?:com|co|io|net|org|ai|app|jp)/\S*",
                     re.IGNORECASE)
EMOJI_RE = re.compile(r"[\U0001F300-\U0001FAFF☀-➿️]")

ASKS = [
    (re.compile(r"[「『\"][^」』\"\n]{1,15}[」』\"]\s*(?:と|って)\s*コメント|コメント(?:して|してね|ください|で|欄に)"),
     "コメント（合言葉）"),
    (re.compile(r"DM(?:して|ください|で|ちょうだい|お待ち)|メッセージ(?:して|ください)"), "DM"),
    (re.compile(r"保存(?:して|しておいて|しといて|推奨|必須|がおすすめ)"), "保存"),
    (re.compile(r"シェア(?:して|してね|ください)|(?:友達|誰か)に(?:送って|教えて)"), "シェア"),
    (re.compile(r"フォロー(?:して|してね|お願い|ください|すると|はこちら)"), "フォロー"),
    (re.compile(r"プロフ(?:ィール)?(?:の|から|欄の)(?:リンク|URL|ＵＲＬ)|プロフから"), "プロフィールのリンク"),
    (re.compile(r"スワイプ(?:して|してね)|(?:右|左)に(?:めくって|スワイプ)"), "スワイプ"),
    (re.compile(r"教えて(?:ね|ください|下さい)?[！!。]?|どっち派|どれ派|どっちが(?:好き|いい)"), "質問に答える"),
]

FILLER_TAGS = {
    "#viral", "#fyp", "#explore", "#explorepage", "#foryou", "#foryoupage", "#trending",
    "#instagood", "#love", "#follow", "#like4like", "#reels", "#reelsinstagram",
    "#viralreels", "#instadaily", "#followme", "#f4f", "#l4l",
    "#おすすめ", "#おすすめにのりたい", "#おすすめ載りたい", "#バズれ", "#バズりたい",
    "#拡散希望", "#いいね返し", "#フォロー返し", "#相互フォロー", "#いいねした人で気になった人フォロー",
    "#リール", "#インスタ", "#インスタグラム", "#instagram", "#フォロー", "#いいね",
}


def visible_window(text, width=LINE_WIDTH, lines=LINES, handle_w=HANDLE_WIDTH):
    """フィードで見える部分。1行目はユーザーネームの分だけ短い。切れる時は最後の行に「…続きを読む」が入る。"""
    flat = text.strip()
    caps = [max(4, width - handle_w - 1)] + [width] * (lines - 1)

    def fit(capacities):
        out, li, used = [], 0, 0
        for c in flat:
            if c == "\n":
                li, used = li + 1, 0
                if li >= len(capacities):
                    return "".join(out), True
                out.append(c)
                continue
            w = jp.width(c)
            if used + w > capacities[li]:
                li, used = li + 1, 0
                if li >= len(capacities):
                    return "".join(out), True
            out.append(c)
            used += w
        return "".join(out), False

    shown, cut = fit(caps)
    if cut:                                        # 最後の行は「…続きを読む」の分だけ短い
        caps[-1] = max(4, caps[-1] - jp.width(TAIL))
        shown, cut = fit(caps)
    return shown, cut


def render_box(window, truncated, out=sys.stdout, width=LINE_WIDTH, handle="ユーザーネーム"):
    print("\n  フィードで見える部分（1行目の頭はユーザーネーム）", file=out)
    print("  +" + "-" * (width + 2) + "+", file=out)
    for line in (handle + " " + window).split("\n"):
        while jp.width(line) > width:              # 表示用の折り返し
            cut, w = 0, 0
            for i, c in enumerate(line):
                w += jp.width(c)
                if w > width:
                    break
                cut = i + 1
            print(f"  | {line[:cut]}{' ' * (width - jp.width(line[:cut]))} |", file=out)
            line = line[cut:]
        print(f"  | {line}{' ' * (width - jp.width(line))} |", file=out)
    tail = TAIL if truncated else "（全部見えている）"
    print("  +" + "-" * max(1, width + 2 - jp.width(tail) - 2) + f" {tail} " + "+", file=out)


def analyse(text, width=LINE_WIDTH, lines=LINES, handle_w=HANDLE_WIDTH, keywords=None,
            handle="ユーザーネーム"):
    text = text.rstrip()
    stripped = text.strip()
    chars = len(stripped)
    first_line = stripped.split("\n")[0].strip() if stripped else ""
    tags = HASHTAG_RE.findall(stripped)
    fw_tags = FULLWIDTH_TAG_RE.findall(stripped)
    mentions = MENTION_RE.findall(stripped)
    links = LINK_RE.findall(stripped)
    emoji = EMOJI_RE.findall(stripped)
    window, truncated = visible_window(stripped, width, lines, handle_w)
    asks = [name for pattern, name in ASKS if pattern.search(stripped)]
    filler = [t for t in tags if t.lower() in FILLER_TAGS]
    keywords = [k.strip() for k in (keywords or []) if k.strip()]

    checks = []

    def add(name, status, detail):
        checks.append({"check": name, "status": status, "detail": detail})

    add("長さ", "FAIL" if chars > LIMIT else "PASS",
        f"{chars} / {LIMIT}字" + (f"、上限を{chars - LIMIT}字超えている" if chars > LIMIT else ""))

    if not first_line:
        add("1行目", "FAIL", "空行から始まっている")
    elif first_line.startswith(("#", "@", "＃")):
        add("1行目", "FAIL", "ハッシュタグかメンションから始まっている。いちばん価値のある場所に文がない")
    elif len(first_line) > len(window.split("\n")[0].strip()):
        add("1行目", "WARN",
            f"{len(first_line)}字あり、見える部分の途中で切れる。"
            "続きが気になる所で切れているなら良し、文の途中の説明で切れているなら悪い")
    else:
        add("1行目", "PASS", f"{len(first_line)}字、切れずに全部見える")

    found = jp.concrete(window)
    add("具体性", "PASS" if found else "WARN",
        f"見える部分に数字・名前が{len(found)}個" + (f"（{', '.join(found[:3])}）" if found else
                                                    "。続きを押す前に確かめられる物がない"))

    if len(tags) > HASHTAG_LIMIT:
        add("ハッシュタグ", "FAIL", f"{len(tags)}個。上限の{HASHTAG_LIMIT}個を超えている。"
                                   "6個目から先は数えられず、ハッシュタグの壁は古く見える")
    elif len(tags) == HASHTAG_LIMIT and filler:
        add("ハッシュタグ", "WARN", f"{len(tags)}個で上限いっぱい、うち{len(filler)}個が何も表さないタグ。"
                                   "5枠はテーマに使う")
    elif filler:
        add("ハッシュタグ", "WARN", f"{len(tags)}個、うち{len(filler)}個が何も表さないタグ"
                                   f"（{', '.join(filler[:3])}）")
    else:
        add("ハッシュタグ", "PASS", f"{len(tags)}個" + (f": {' '.join(tags)}" if tags else ""))
    if fw_tags:
        add("全角の＃", "WARN", f"{len(fw_tags)}個（{' '.join(fw_tags[:3])}）。全角の＃はハッシュタグに"
                                "ならない。半角の # にする")

    if not tags:
        add("タグの位置", "PASS", "置くタグがない")
    elif any(t in window for t in tags):
        add("タグの位置", "WARN", "見える部分にハッシュタグがある。フィードの場所をラベルに使っている")
    else:
        add("タグの位置", "PASS", "タグは「続きを読む」の後ろ")

    add("リンク", "WARN" if links else "PASS",
        f"キャプションにリンクが{len(links)}個。キャプションのリンクは押せない。"
        "プロフィールか DM に移す" if links else "押せないリンクはない")

    if len(asks) == 1:
        add("お願いは1つ", "PASS", f"お願いは1つ: {asks[0]}")
    elif not asks:
        add("お願いは1つ", "WARN", "お願いがない。この投稿が何のためにあるかを決める")
    else:
        add("お願いは1つ", "WARN", f"お願いが{len(asks)}つ（{', '.join(asks)}）。2つのお願いは、ないのと同じ")

    density = len(emoji) * 100 / max(chars, 1)
    add("絵文字", "WARN" if density > 5 else "PASS",
        f"{len(emoji)}個、100字あたり{density:.1f}個" + ("。飾りに見える" if density > 5 else ""))

    if keywords:
        found_k = [k for k in keywords if k.lower() in stripped.lower()]
        missing = [k for k in keywords if k.lower() not in stripped.lower()]
        in_window = [k for k in found_k if k.lower() in window.lower()]
        status = "PASS" if not missing else ("WARN" if found_k else "FAIL")
        add("検索される言葉", status,
            f"{len(found_k)}/{len(keywords)}個入っている"
            + (f"、うち見える部分に{len(in_window)}個" if found_k else "")
            + (f"。入っていない: {', '.join(missing)}" if missing else ""))

    fails = sum(1 for c in checks if c["status"] == "FAIL")
    warns = sum(1 for c in checks if c["status"] == "WARN")
    verdict = "FIX" if fails else ("REVIEW" if warns else "READY")

    return {
        "characters": chars, "limit": LIMIT,
        "line_width": width, "lines": lines, "handle": handle,
        "visible": window, "truncated": truncated,
        "first_line_chars": len(first_line),
        "hashtags": tags, "mentions": mentions, "links": links,
        "emoji": len(emoji), "asks": asks,
        "checks": checks, "verdict": verdict,
    }


STATUS_JA = {"PASS": "OK  ", "WARN": "注意", "FAIL": "NG  "}
VERDICT_JA = {"READY": "出せる", "REVIEW": "見直す", "FIX": "直す"}


def render(a, out=sys.stdout):
    head = (f"キャプションの検査  ·  {a['characters']} / {a['limit']}字  ·  "
            f"ハッシュタグ{len(a['hashtags'])}個  ·  お願い{len(a['asks'])}つ")
    print("\n" + head, file=out)
    print("=" * 62, file=out)
    render_box(a["visible"], a["truncated"], out=out, width=a["line_width"], handle=a["handle"])
    print("", file=out)
    for c in a["checks"]:
        name = c["check"] + " " * max(0, 16 - jp.width(c["check"]))
        print(f"  {STATUS_JA[c['status']]}  {name} {c['detail']}", file=out)
    print("-" * 62, file=out)
    print(f"  判定  {VERDICT_JA[a['verdict']]}\n", file=out)


def main():
    ap = argparse.ArgumentParser(description="インスタのキャプションを検査する（日本語版）。")
    ap.add_argument("input", nargs="?", default="-", help="キャプションのファイル。- で標準入力")
    ap.add_argument("--width", type=int, default=LINE_WIDTH,
                    help=f"1行の幅。全角2・半角1で数える（初期値 {LINE_WIDTH}＝全角約23字）")
    ap.add_argument("--lines", type=int, default=LINES,
                    help=f"「続きを読む」の前に見える行数（初期値 {LINES}。リールの画面は1）")
    ap.add_argument("--handle", default=None, help="1行目の頭に出るユーザーネーム（幅の計算に使う）")
    ap.add_argument("--keywords", default="", help="見つけてほしい言葉。カンマ区切り")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    raw = sys.stdin.read() if args.input == "-" else open(args.input, encoding="utf-8").read()
    handle_w = jp.width(args.handle) if args.handle else HANDLE_WIDTH
    a = analyse(raw, width=args.width, lines=args.lines, handle_w=handle_w,
                keywords=re.split(r"[,、，]", args.keywords),
                handle=args.handle or "ユーザーネーム")
    if args.json:
        print(json.dumps(a, indent=2, ensure_ascii=False))
    else:
        render(a)
    sys.exit(0 if a["verdict"] == "READY" else 1)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    main()
