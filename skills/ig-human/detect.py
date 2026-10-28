#!/usr/bin/env python3
"""
detect.py - 下書きがどれだけ機械っぽく見えるかを、5つの項目で採点する。日本語版。

これは何か: 公開されているAI判定が見ている合図をまねた、5つの目安。文の長さの
ばらつき、具体性、決まり文句、記号の跡、話し手の声。どの点数も文字だけから
手元のPCで計算する。何も送信しない。

これは何でないか: GPTZero・Originality・Copyleaks・Winston・Turnitin ではない。
それらに問い合わせないし、その判定を約束できない。それらが共通して見ている物を
拾うので、ここを直すと向こうの数字も動きやすい。言えるのはそこまで。

日本語版の基準は、日本語の投稿（人が書いて伸びた物）と、AIの定番の書き方で
書いた文を比べて決めた（README の「日本語版で測ったこと」）。

各項目は「人らしさ」の0〜100。高いほど良い。

使い方
  python3 detect.py draft.txt
  python3 detect.py draft.txt --json
  python3 detect.py before.txt after.txt      # 2つを比べる
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
MIN_CHARS = 60           # これより短いと、密度の項目は判断しない

# 話し言葉の目印。英語版の「短縮形（don't など）」に当たる、日本語の話し手の声。
SPOKEN_RE = re.compile(
    r"よね|よ[。！!？?\n]|ね[。！!？?\n]|じゃん|けど|かも|だよ|んだ|んです|んじゃ|っす|"
    r"ちゃう|ちゃった|ちゃい|てる|てた|でしょ|かな[。！!？?\n]|だろ|なぁ|なあ|笑|ｗ|w{2,}|"
    r"やん|へん|ねん|わ[。！!\n]|ぞ[。！!\n]|マジ|めっちゃ|ガチ|やっぱ|ほんと|って[。！!、]")
PERSON_RE = re.compile(r"僕|ぼく|私|わたし|俺|おれ|自分|うち(?:の|は|も)|あなた|みんな|君")


def clamp(n):
    return max(0.0, min(100.0, n))


def scale(value, human, machine):
    """value を0〜100に。human の値で100、machine の値で0。"""
    if human == machine:
        return 50.0
    return clamp((value - machine) / (human - machine) * 100)


def ending(sentence):
    s = re.sub(r"[。．！？!?…」』）)\s]+$", "", sentence)
    return s[-2:] if len(s) >= 2 else s


def body_chars(text):
    return len(re.sub(r"\s", "", text))


LIST_LINE = re.compile(r"^\s*(?:[・\-－*•✅❌☑▶►→①-⑳]|[0-9０-９]+[.)．）]|【[^】]*】\s*$)")


def prose(text):
    """箇条書きの行と【見出し】だけの行を除いた本文。箇条書きはそろって当然なので、ばらつきに数えない。"""
    return "\n".join(l for l in text.splitlines() if not LIST_LINE.match(l))


def check_burstiness(text):
    """人は文の長さを大きく変える。機械はそろえる。"""
    lens = [len(s) for s in jp.sentences(prose(text))]
    if len(lens) < 4:
        return 50.0, "短すぎて判断できない"
    mean = statistics.mean(lens)
    cv = statistics.pstdev(lens) / mean if mean else 0
    score = scale(cv, human=0.60, machine=0.20)
    return score, f"{len(lens)}文の長さのばらつき {cv:.2f}（0.5以上がほしい）"


def check_specificity(text):
    """数字・名前・具体的な物。決まり文句はぼんやりしている。"""
    n = body_chars(text)
    if n < MIN_CHARS:
        return 50.0, "短すぎて判断できない"
    hits = jp.concrete(text)
    density = len(hits) * 100 / n
    score = scale(density, human=1.5, machine=0.1)
    return score, f"具体的な目印 {len(hits)}個、100字あたり{density:.1f}個（1以上がほしい）"


def check_slop(text, lex):
    """決まり文句の密度。"""
    n = body_chars(text)
    if not n:
        return 50.0, "空"
    hits, found = 0, []
    for entry in lex["words"] + lex["phrases"]:
        k = text.count(entry["find"])
        if k:
            hits += k
            found.append(entry["find"])
    density = hits * 100 / n
    score = scale(density, human=0.0, machine=1.5)
    detail = f"決まり文句 {hits}個、100字あたり{density:.1f}個"
    if found:
        detail += "（" + "、".join(sorted(found, key=len, reverse=True)[:4]) + ("…" if len(found) > 4 else "") + "）"
    return score, detail


def check_fingerprint(text):
    """スマホのキーボードでは打てない文字・AIの書式の跡。"""
    invisible = sum(1 for c in text if unicodedata.category(c) == "Cf" and c != "‍")
    dash = len(re.findall(r"[—―]+", text))
    curly = sum(text.count(c) for c in "“”‘’")
    md = text.count("**") // 2 + len(re.findall(r"(?m)^\s*#{1,6}\s+\S", text))
    nbsp = sum(text.count(c) for c in "   ")
    total = invisible * 4 + dash * 2 + curly + md * 2 + nbsp
    per1k = total * 1000 / max(len(text), 1)
    score = scale(per1k, human=0.0, machine=12.0)
    detail = (f"見えない文字{invisible}・長いダッシュ{dash}・英語のかぎ{curly}・"
              f"マークダウン{md}・特殊な空白{nbsp}")
    return score, detail


def check_voice(text, lex):
    """話し手の声。話し言葉・人称・文末の変化と、AIが好む文の形。"""
    n = body_chars(text)
    if n < MIN_CHARS:
        return 50.0, "短すぎて判断できない"
    per100 = 100 / n
    spoken = len(SPOKEN_RE.findall(text)) * per100
    person = len(PERSON_RE.findall(text)) * per100
    sents = jp.sentences(text)
    ends = [ending(s) for s in sents]
    variety = len(set(ends)) / len(ends) if ends else 1.0
    tells, names = 0, []
    for s in lex["structures"]:
        try:
            k = len(re.compile(s["regex"]).findall(text))
        except re.error:
            continue
        if k:
            tells += k
            names.append(s["id"])
    run, longest = 1, 1
    for a, b in zip(ends, ends[1:]):
        run = run + 1 if a == b and a else 1
        longest = max(longest, run)
    if longest >= 3:
        tells += longest - 2
        names.append("same-ending")
    score = (scale(spoken, human=2.0, machine=0.0) * 0.30
             + scale(person, human=1.0, machine=0.0) * 0.15
             + scale(variety, human=0.85, machine=0.35) * 0.25
             + clamp(100 - tells * 20) * 0.30)
    detail = (f"話し言葉{spoken:.1f}・人称{person:.1f}（100字あたり）、"
              f"文末の種類{variety:.0%}、文の形の跡{tells}個")
    if names:
        detail += " [" + ", ".join(names[:4]) + "]"
    return clamp(score), detail


CHECKS = ["BURSTINESS", "SPECIFICITY", "SLOP DENSITY", "FINGERPRINT", "VOICE"]
LABELS = {"BURSTINESS": "文のばらつき", "SPECIFICITY": "具体性", "SLOP DENSITY": "決まり文句",
          "FINGERPRINT": "記号の跡", "VOICE": "話し手の声"}


def run(text, lex):
    results = {
        "BURSTINESS": check_burstiness(text),
        "SPECIFICITY": check_specificity(text),
        "SLOP DENSITY": check_slop(text, lex),
        "FINGERPRINT": check_fingerprint(text),
        "VOICE": check_voice(text, lex),
    }
    scores = [results[c][0] for c in CHECKS]
    # いちばん弱い項目が判定を引っぱる。判定する側は合図が1つあれば足りる。
    overall = statistics.mean(scores) * 0.6 + min(scores) * 0.4
    verdict = "PASS" if overall >= 70 and min(scores) >= 55 else (
        "REVIEW" if overall >= 50 else "FLAGGED")
    return results, overall, verdict


VERDICT_JA = {"PASS": "合格", "REVIEW": "見直す", "FLAGGED": "AIっぽい"}


def bar(score, width=24):
    filled = round(score / 100 * width)
    return "#" * filled + "." * (width - filled)


def pad(s, n):
    return s + " " * max(0, n - jp.width(s))


def render(results, overall, verdict, label=None, out=sys.stdout):
    title = "AIっぽさの判定" + (f"  -  {label}" if label else "")
    print("\n" + title, file=out)
    print("=" * 62, file=out)
    for name in CHECKS:
        score, detail = results[name]
        print(f"  {pad(LABELS[name], 13)} {bar(score)} {score:5.1f}", file=out)
        print(f"  {'':<13} {detail}", file=out)
    print("-" * 62, file=out)
    print(f"  {pad('人らしさ', 13)} {bar(overall)} {overall:5.1f}   {VERDICT_JA[verdict]}", file=out)
    if verdict != "PASS":
        weakest = min(CHECKS, key=lambda c: results[c][0])
        print(f"\n  いちばん弱いのは「{LABELS[weakest]}」。そこから直す。", file=out)
    print("", file=out)


def main():
    ap = argparse.ArgumentParser(description="下書きの機械っぽさを採点する（日本語版）。")
    ap.add_argument("input", nargs="?", default="-", help="ファイル。- で標準入力")
    ap.add_argument("compare", nargs="?", help="比べる2つ目のファイル（前後の比較）")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--lexicon", default=LEX)
    args = ap.parse_args()

    lex = json.load(open(args.lexicon, encoding="utf-8"))
    read = lambda p: sys.stdin.read() if p == "-" else open(p, encoding="utf-8").read()  # noqa: E731

    targets = [(args.input, read(args.input))]
    if args.compare:
        targets.append((args.compare, read(args.compare)))

    payload = []
    for name, text in targets:
        results, overall, verdict = run(text, lex)
        payload.append({
            "source": name,
            "checks": {k: {"score": round(v[0], 1), "detail": v[1]} for k, v in results.items()},
            "human_score": round(overall, 1),
            "verdict": verdict,
        })

    if args.json:
        print(json.dumps(payload if args.compare else payload[0], indent=2, ensure_ascii=False))
        return

    for (name, text), p in zip(targets, payload):
        results, overall, verdict = run(text, lex)
        render(results, overall, verdict, label=os.path.basename(name) if args.compare else None)
    if args.compare:
        a, b = payload
        delta = b["human_score"] - a["human_score"]
        print(f"  {a['human_score']:.1f} {VERDICT_JA[a['verdict']]}  ->  "
              f"{b['human_score']:.1f} {VERDICT_JA[b['verdict']]}   ({delta:+.1f})\n")

    sys.exit(0 if payload[-1]["verdict"] == "PASS" else 1)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    main()
