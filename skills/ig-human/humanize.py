#!/usr/bin/env python3
"""
humanize.py - 下書きから、機械が書いた跡を消す。日本語版。

この順に3回通す。

  1. 見えない文字  キーボードでは打てない文字を消すか、ふつうの空白にする。
                   幅ゼロの空白、つなぎ文字、ソフトハイフン、BOM、タグ文字、
                   改行しない空白など。コピーしても残り、生成文のいちばん機械的な跡。
                   全角の空白（U+3000）は日本語でふつうに使うので触らない。
                   絵文字どうしをつなぐ文字（家族の絵文字など）も残す。
  2. 記号          長いダッシュ（— ―）→「、」、数字の間の短いダッシュ → 「〜」、
                   英語のかぎ（“”）→「」、黒丸（•）→「・」、マークダウンの太字（**）
                   と見出し記号（##）を消す。三点リーダー（…）と矢印（→）は日本語で
                   ふつうに使うので触らない。
  3. 言い回し      slop.json の決まり文句を、ふつうの言い方に置き換える。
                   日本語は活用で形が変わるので、文が壊れない単位（「することができ」
                   →「でき」など）で置き換える。リンクの中は触らない。

文の形の跡（3つ並べ、「〜だけでなく〜も」、文末が同じ形の連続など）は、知らせる
だけで書き換えない。文の形を変えるには判断が要るので、それは正規表現ではなく
AI（あなた）の仕事。

使い方
  python3 humanize.py draft.txt
  python3 humanize.py draft.txt --report
  python3 humanize.py draft.txt -o clean.txt --report
  python3 humanize.py draft.txt --json
"""

import argparse
import json
import os
import re
import statistics
import sys
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import jp  # noqa: E402

LEX = os.path.join(HERE, "slop.json")
URL_RE = re.compile(r"https?://\S+|www\.\S+|\S+@\S+\.\S+")
EMOJI_CP = re.compile(r"[\U0001F000-\U0001FAFF☀-➿]")
ZWJ = "‍"


def load_lexicon(path=LEX):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _cp(spec):
    """'U+200B' -> 0x200b、'U+E0000-U+E007F' -> (始め, 終わり)"""
    if "-" in spec:
        a, b = spec.split("-")
        return (int(a[2:], 16), int(b[2:], 16))
    return int(spec[2:], 16)


def protect_urls(text):
    """どの処理もリンクの中を書き換えないように、リンクを目印に置き換えておく。"""
    found = []

    def stash(m):
        found.append(m.group(0))
        return f"\x00URL{len(found) - 1}\x00"

    return URL_RE.sub(stash, text), found


def restore_urls(text, found):
    for i, url in enumerate(found):
        text = text.replace(f"\x00URL{i}\x00", url)
    return text


def _emoji_zwj_mask(text):
    """絵文字どうしをつなぐ ZWJ の位置。ここは消さない。"""
    keep = set()
    for i, c in enumerate(text):
        if c == ZWJ and 0 < i < len(text) - 1:
            prev = text[i - 1]
            if prev == "️" and i > 1:
                prev = text[i - 2]
            if EMOJI_CP.match(prev) and EMOJI_CP.match(text[i + 1]):
                keep.add(i)
    return keep


def pass_invisible(text, lex):
    """見えない文字を消すか空白にする。(text, 記録) を返す。"""
    hits = []
    keep = _emoji_zwj_mask(text)
    if keep:
        text = "".join("\x00ZWJ\x00" if i in keep else c for i, c in enumerate(text))
    for entry in lex["invisible"]:
        cp = _cp(entry["cp"])
        if isinstance(cp, tuple):
            pattern = "[" + re.escape(chr(cp[0])) + "-" + re.escape(chr(cp[1])) + "]"
        else:
            pattern = re.escape(chr(cp))
        n = len(re.findall(pattern, text))
        if n:
            hits.append({"name": entry["cp"] + " " + entry["name"], "count": n,
                         "action": entry["action"]})
            text = re.sub(pattern, "" if entry["action"] == "delete" else " ", text)
    # 残った書式文字（Cf）は、名前が分からなくても見えない文字。
    stray = [c for c in text if unicodedata.category(c) == "Cf"]
    if stray:
        hits.append({"name": "その他の見えない書式文字", "count": len(stray), "action": "delete"})
        text = "".join(c for c in text if unicodedata.category(c) != "Cf")
    return text.replace("\x00ZWJ\x00", ZWJ), hits


def pass_typographic(text, lex):
    hits = []
    for entry in lex["typographic"]:
        ch = entry["from"]
        n = text.count(ch)
        if not n:
            continue
        hits.append({"name": f"{ch} {entry['name']}", "count": n, "to": entry["to"] or "（消す）"})
        if ch in ("—", "―"):
            # 文の終わりの後のダッシュは「。」、それ以外は「、」。
            text = re.sub(r"\s*[—―]+\s*", "\x00D\x00", text)
            text = re.sub(r"(です|ます|でした|ました|ません|だ|った|ない|よ|ね)\x00D\x00", r"\1。", text)
            text = text.replace("\x00D\x00", "、")
        elif ch == "–":
            text = re.sub(r"(?<=\d)\s*–\s*(?=\d)", "〜", text)     # 5–10 -> 5〜10
            text = text.replace("–", "-")
        else:
            text = text.replace(ch, entry["to"])
    heads = len(re.findall(r"(?m)^[ \t]*#{1,6}[ \t]+(?=\S)", text))
    if heads:
        hits.append({"name": "## マークダウンの見出し記号", "count": heads, "to": "（消す）"})
        text = re.sub(r"(?m)^[ \t]*#{1,6}[ \t]+(?=\S)", "", text)
    # ダッシュを「、」にした後の、句読点の重なりを直す。
    text = re.sub(r"、\s*([、。！？!?」])", r"\1", text)
    text = re.sub(r"(?m)^、", "", text)
    text = re.sub(r"、\n", "\n", text)
    return text, hits


def pass_lexical(text, lex):
    """決まり文句を置き換える。長い物から先に（言い回しの単位を優先）。"""
    hits = []
    entries = sorted(lex["phrases"] + lex["words"], key=lambda e: len(e["find"]), reverse=True)
    for entry in entries:
        find = entry["find"]
        n = text.count(find)
        if not n:
            continue
        hits.append({"find": find, "replace": entry["replace"] or "（消す）",
                     "count": n, "family": entry["family"]})
        text = text.replace(find, entry["replace"])
    # 消した後の後始末。消えた言い回しの句読点が残ると、元より読みにくい。
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"(?m)^[ \t]*[、。，．]+[ \t]*", "", text)
    text = re.sub(r"[、，]\s*([、。！？!?])", r"\1", text)
    text = re.sub(r"。\s*。+", "。", text)
    text = re.sub(r"([！？!?])\s*。", r"\1", text)
    text = re.sub(r"(?m)^[ \t]*[！？!?。、]+[ \t]*$", "", text)   # 消した文の句読点だけが残った行
    text = re.sub(r"(?m)^[ \t]+$", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text, hits


def ending(sentence):
    """文末の形（句読点の前の2文字）。"""
    s = re.sub(r"[。．！？!?…」』）)\s]+$", "", sentence)
    return s[-2:] if len(s) >= 2 else s


def scan_structures(text, lex):
    flags = []
    for s in lex["structures"]:
        try:
            pattern = re.compile(s["regex"])
        except re.error:
            continue
        found = pattern.findall(text)
        if found:
            flags.append({"name": s["name"], "count": len(found), "fix": s["fix"]})
    sents = jp.sentences(text)
    # 文末が同じ形で3回以上続く（「〜ます。〜ます。〜ます。」）。
    run, longest, form = 1, 1, ""
    ends = [ending(s) for s in sents]
    for a, b in zip(ends, ends[1:]):
        run = run + 1 if a == b and a else 1
        if run > longest:
            longest, form = run, b
    if longest >= 3:
        flags.append({
            "name": f"文末が{longest}回続けて同じ形（〜{form}）",
            "count": longest,
            "fix": "どれか1文の終わりを変える。言い切り・体言止め・問いかけ・「ね」「よ」を混ぜる。",
        })
    # 文の長さがそろいすぎている。
    lens = [len(s) for s in sents]
    if len(lens) >= 4:
        mean = statistics.mean(lens)
        cv = statistics.pstdev(lens) / mean if mean else 0
        if cv < 0.25:
            flags.append({
                "name": f"文の長さがそろいすぎ（ばらつき {cv:.2f}）",
                "count": len(lens),
                "fix": "1文を半分に切る。別の1文は長くしていい。機械は同じ長さで書く。",
            })
    return flags


def humanize(text, lex):
    text, urls = protect_urls(text)
    text, inv = pass_invisible(text, lex)
    text, typo = pass_typographic(text, lex)
    text, lexi = pass_lexical(text, lex)
    text = restore_urls(text, urls)
    return text.strip() + "\n", {
        "invisible": inv,
        "typographic": typo,
        "lexical": lexi,
        "structures": scan_structures(text, lex),
    }


def render_report(report, out=sys.stderr):
    def head(title):
        print(f"\n{title}\n" + "-" * 40, file=out)

    total = sum(h["count"] for h in report["invisible"]) \
        + sum(h["count"] for h in report["typographic"]) \
        + sum(h["count"] for h in report["lexical"])

    head("AIっぽさ消しの記録")
    print(f"機械の跡を{total}か所消した。文の形の跡は{len(report['structures'])}種類、"
          "書き直し用に知らせる", file=out)

    if report["invisible"]:
        head("1. 見えない文字")
        for h in report["invisible"]:
            print(f"  {h['count']:>3}か所  {h['name']}  -> {h['action']}", file=out)
    if report["typographic"]:
        head("2. 記号")
        for h in report["typographic"]:
            print(f"  {h['count']:>3}か所  {h['name']}  -> {h['to']}", file=out)
    if report["lexical"]:
        head("3. 決まり文句")
        for h in report["lexical"]:
            print(f"  {h['count']:>3}か所  {h['find']}  -> {h['replace']}   [{h['family']}]", file=out)
    if report["structures"]:
        head("4. 文の形の跡（自動では直さない。自分で書き直す）")
        for h in report["structures"]:
            print(f"  {h['count']:>3}回  {h['name']}\n        {h['fix']}", file=out)
    if not any(report.values()):
        head("きれい")
        print("  消す物はなかった。", file=out)
    print("", file=out)


def main():
    ap = argparse.ArgumentParser(description="下書きから機械の跡を消す（日本語版）。")
    ap.add_argument("input", nargs="?", default="-", help="ファイル。- で標準入力")
    ap.add_argument("-o", "--out", help="直した文をここに書く（指定しなければ画面に出す）")
    ap.add_argument("--report", action="store_true", help="何を変えたかを出す")
    ap.add_argument("--json", action="store_true", help="{text, report} を JSON で出す")
    ap.add_argument("--lexicon", default=LEX, help="slop.json の場所")
    args = ap.parse_args()

    raw = sys.stdin.read() if args.input == "-" else open(args.input, encoding="utf-8").read()
    lex = load_lexicon(args.lexicon)
    clean, report = humanize(raw, lex)

    if args.json:
        print(json.dumps({"text": clean, "report": report}, indent=2, ensure_ascii=False))
        return
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(clean)
        print(f"書き出し: {args.out}", file=sys.stderr)
    else:
        sys.stdout.write(clean)
    if args.report:
        render_report(report)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    main()
