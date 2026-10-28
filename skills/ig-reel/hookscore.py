#!/usr/bin/env python3
"""
hookscore.py - リールの1行目（フック）を、強いフックに共通する5つの性質で
採点し、何案かを並べて順位をつける。日本語版。

これは何か: 文字だけから、手元のPCで計算する5つの目安。2〜3秒で言い切れる
長さ、具体的な目印（数字・名前）、何かが懸かっていること、肝心の言葉が前に
あること、見ている人に向いていること。

これは何でないか: 再生数の予測ではない。英語版は実際のフック74本で試して、
「わざと下手に書いたフック」を見分けるのは得意（AUC 0.83）、「同じ人の当たりと
外れ」を見分けるのはほぼできない（AUC 0.56。0.50がコイン投げ）という結果だった。
日本語版の試験の結果は README の「日本語版で測ったこと」にある。

使い道は、言い切れない・中身がない・あいさつから入る・長すぎるフックを、撮る前に
落とすこと。まあまあのフック2つのどちらが伸びるかは、文字からは分からない。
顔・編集・音・インスタが誰に見せるかで決まる。最後は自分の視聴維持のグラフを信じる。

各項目は0〜100。高いほど良い。

使い方
  python3 hookscore.py hooks.txt              # 1行に1案。順位をつける
  python3 hookscore.py --hook "契約書の1行で20万円損しました"
  python3 hookscore.py hooks.txt --cps 10     # 話す速さ（1秒に話すかなの数）
  python3 hookscore.py hooks.txt --json
"""

import argparse
import json
import os
import re
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import jp  # noqa: E402

DEFAULT_CPS = 9.0       # 1秒に話すかなの数。撮る前の素の速さ。カット編集後は約10

# 何かが懸かっている言葉。どれも入っていなければただの説明、1つあれば見続ける理由。
STAKES = [
    "損", "失敗", "間違", "後悔", "危険", "危な", "ヤバ", "やば", "終わ", "消え",
    "無料", "タダ", "無駄", "誰も", "知らな", "知らず", "実は", "本当は", "ほんとは",
    "嘘", "ウソ", "秘密", "裏", "禁止", "NG", "ダメ", "だめ", "やめ", "辞め", "捨て",
    "負け", "失っ", "失う", "炎上", "最悪", "地獄", "しないと", "しなきゃ", "なのに",
    "だけど", "けど", "でも", "まだ", "もう", "二度と", "絶対", "クビ", "解約", "削除",
    "卒業", "不要", "いらない", "要らない", "置き換", "代わり", "奪", "倒", "勝て",
    "稼", "払っ", "払う", "盗", "パクっ", "パクれ", "バレ", "怒", "嫌", "下手", "遅れ",
    "差がつ", "変わ", "しかない", "だけで", "ずに", "せずに", "なしで", "以外",
    "逆に", "勘違い", "落とし穴", "注意", "警告", "知ってる", "知って", "知りたかった",
    "衝撃", "驚", "まさか", "正直", "本音", "現実", "真実", "なぜ", "唯一", "初めて",
    "前に", "までに", "代わりに", "それより", "ではなく", "じゃなく", "のに",
    "今は", "今では", "前は", "昔は", "だけ", "たった", "ついに", "ゼロ", "0円",
]
STAKES_RE = re.compile("|".join(map(re.escape, STAKES)))
NEG_RE = re.compile(r"ない|ません|なかった|ねえ|ねぇ")

# 最初の1秒を何も言わずに使ってしまう出だし。
WEAK_OPENERS = [
    "えー", "えっと", "あの", "あのー", "はい", "どうも", "こんにちは", "こんばんは",
    "おはよう", "みなさん", "皆さん", "今日は", "今回は", "本日は", "さて", "ということで",
    "というわけで", "突然ですが", "早速ですが", "さっそく", "最近", "ちなみに", "まず",
    "今日の", "今回の", "これから", "今から", "では",
]

# 相手に向いている形。命令・お願い・問いかけ・「〜な人」の呼びかけ。
ADDRESS_YOU = re.compile(r"あなた|君|きみ|お前|おまえ|アナタ")
ADDRESS_CALL = re.compile(
    r"(?:な|てる|ている|でる|の|する|した|い|た)(?:人|方)(?:へ|は|、|！|!|って|いる|いない|必見|に|[。？?]|$)|"
    r"(?:女性|男性|ママ|パパ|さん|たち|ども|子)へ(?:[。！!、]|$)|^\s*(?:いいか|聞いて|見て)[、！!]")
ADDRESS_ACT = re.compile(
    r"(?:して|しろ|するな|しないで|やめて|見て|使って|やって|試して|聞いて|消して|保存して|"
    r"てください|なさい|ましょう|べき|せよ|すな|ないで|しとけ|とけ)(?:[。！？!?」\s]|$)|"
    r"(?:ませんか|てない|知ってる|知ってた|わかる|分かる|どっち|どれ|ですか|ますか)[？?]")
ADDRESS_IF = re.compile(r"^[^。！？\n]{2,30}(?:なら|たら|れば)[、,\s]")
ADDRESS_I = re.compile(r"僕|ぼく|私|わたし|俺|おれ|自分|うち|我々")

DEALBREAKERS = [
    (re.compile(r"^\s*(?:ちょっと待って|待って[！!、]|スクロール(?:しないで|を止めて|する手を止めて|やめて)|最後まで見て|見逃さないで)"),
     "注目をお願いする出だし（「ちょっと待って」「最後まで見て」）。注目を頼むのは、まだ掴めていない証拠。"),
    (re.compile(r"この動画では|今回の動画では|今日の動画では|(?:今日|今回)は[^。！？\n]{0,25}(?:紹介|解説|お話し|話)(?:します|していきます|しようと思います)"),
     "動画の前置き（「今日は〜を紹介します」）。消して、答えから始める。"),
    (re.compile(r"^\s*(?:はいどうも|どうも[、,！!]|どうも[^。、]{0,12}です|こんにちは|こんばんは|おはようございます|はじめまして|みなさんこんにちは)"),
     "あいさつ。あいさつを聞きにフィードを見ている人はいない。"),
    (re.compile(r"(?:^|[\s　])[#＃][^\s#＃]+"),
     "フックにハッシュタグ。ハッシュタグはキャプションの最後に置く物。"),
    (re.compile(r"[\U0001F300-\U0001FAFF☀-➿]"),
     "フックに絵文字。フックの大きさのテロップに、言葉と絵文字の両方を置く場所はない。"),
]


def clamp(n):
    return max(0.0, min(100.0, n))


def check_length(text, cps):
    """指が動く前に言い切れるか。2〜3秒が目安。"""
    mora = jp.yomi(text)
    secs = mora / cps
    chars = len(re.sub(r"\s", "", text))
    if 8 <= mora <= 26:
        score = 100.0
    elif mora < 8:
        score = clamp(100 - (8 - mora) * 10)
    else:
        score = clamp(100 - (mora - 26) * 4)
    if chars > 26:                       # 大きなテロップで2行を超える
        score -= 12
    return clamp(score), f"{chars}字・読み約{mora:.0f}音・話すと約{secs:.1f}秒（目安は8〜26音＝約1〜3秒）"


def check_specificity(text):
    """具体的な1つは、ぼんやりした3つに勝つ。"""
    found = jp.concrete(text)
    hits = len(found)
    score = 15.0 if hits == 0 else clamp(45 + hits * 30)
    return score, (f"具体的な目印 {hits}個" + (f": {', '.join(found[:3])}" if found else
                   "（数字も名前もない。確かめられる物が何もない）"))


def check_stakes(text):
    """緊張・損・否定。見ている人が失うかもしれない何か。"""
    markers = sorted(set(STAKES_RE.findall(text)))
    if NEG_RE.search(text):
        markers.append("否定")
    if re.search(r"[0-9０-９][0-9０-９,]*\s?(?:万|億)?円|[$¥￥]\s?[0-9]", text):
        markers.append("金額")
    n = len(markers)
    score = {0: 20.0, 1: 70.0}.get(n, 100.0)
    detail = f"懸かっている物の目印 {n}個" + (f": {', '.join(markers[:4])}" if markers else
                                               "（この1行には何も懸かっていない）")
    return clamp(score), detail


def _payload_pos(text):
    """肝心の言葉（数字・名前・懸かっている言葉）が何文字目に出てくるか。"""
    pos = []
    for m in STAKES_RE.finditer(text):
        pos.append(m.start())
    for m in jp.NUM_RE.finditer(text):
        pos.append(m.start())
    for m in jp.KANJI_NUM_RE.finditer(text):
        pos.append(m.start())
    for m in jp.LATIN_NAME_RE.finditer(text):
        if m.group(0).strip() not in jp.GENERIC_LATIN and len(m.group(0).strip()) >= 2:
            pos.append(m.start())
    for m in jp.QUOTED_RE.finditer(text):
        pos.append(m.start())
    return min(pos) if pos else None


def check_frontload(text):
    """面白い言葉が後ろにあると、そこまで聞いてもらえない。"""
    t = text.strip()
    if not t:
        return 0.0, "空"
    penalty, hit = 0, None
    for weak in WEAK_OPENERS:
        if t.startswith(weak):
            penalty, hit = 30, weak
            break
    p = _payload_pos(t)
    if p is None:
        base, where = 30.0, "肝心の言葉がどこにもない"
    elif p <= 6:
        base, where = 100.0, f"肝心の言葉が{p + 1}文字目"
    elif p <= 12:
        base, where = 70.0, f"肝心の言葉が{p + 1}文字目。もっと前に出せる"
    else:
        base, where = 40.0, f"肝心の言葉が{p + 1}文字目。遅すぎる"
    return clamp(base - penalty), where + (f"／弱い出だし「{hit}」" if hit else "")


def check_address(text):
    """見ている1人に向けているか、宙に浮いているか。"""
    if ADDRESS_YOU.search(text) or ADDRESS_CALL.search(text):
        return 100.0, "見ている人に向けている"
    if ADDRESS_ACT.search(text):
        return 90.0, "命令・お願い・問いかけで相手に向けている"
    if ADDRESS_IF.search(text):
        return 90.0, "「〜なら」の条件で、見ている人を指している"
    if ADDRESS_I.search(text):
        return 70.0, "一人称。見ている人は出てこない"
    return 55.0, "誰に向けた言葉か書いていない（日本語は主語を省くのが普通なので、英語版の35点より甘くしている）"


CHECKS = ["LENGTH", "SPECIFICITY", "STAKES", "FRONTLOAD", "ADDRESS"]
LABELS = {"LENGTH": "長さ", "SPECIFICITY": "具体性", "STAKES": "懸かっている物",
          "FRONTLOAD": "前に置く", "ADDRESS": "相手に向く"}


def run(text, cps=DEFAULT_CPS):
    results = {
        "LENGTH": check_length(text, cps),
        "SPECIFICITY": check_specificity(text),
        "STAKES": check_stakes(text),
        "FRONTLOAD": check_frontload(text),
        "ADDRESS": check_address(text),
    }
    flags = [msg for pattern, msg in DEALBREAKERS if pattern.search(text)]
    scores = [results[c][0] for c in CHECKS]
    # いちばん弱い性質がフックの上限になる（detect.py と同じ考え方）。
    # 1つでも弱いと、指は止まらない。
    overall = statistics.mean(scores) * 0.6 + min(scores) * 0.4 - len(flags) * 15
    overall = clamp(overall)
    verdict = "STRONG" if overall >= 70 and min(scores) >= 55 and not flags else (
        "OK" if overall >= 50 else "WEAK")
    return results, overall, verdict, flags


VERDICT_JA = {"STRONG": "強い", "OK": "まあまあ", "WEAK": "弱い"}


def bar(score, width=24):
    filled = round(score / 100 * width)
    return "#" * filled + "." * (width - filled)


def pad(s, n):
    """全角を2として幅をそろえる。"""
    return s + " " * max(0, n - jp.width(s))


def render_one(text, results, overall, verdict, flags, out=sys.stdout):
    print("\nフックの点数", file=out)
    print("=" * 62, file=out)
    print(f"  「{text.strip()}」\n", file=out)
    for name in CHECKS:
        score, detail = results[name]
        print(f"  {pad(LABELS[name], 14)} {bar(score)} {score:5.1f}", file=out)
        print(f"  {'':<14} {detail}", file=out)
    print("-" * 62, file=out)
    print(f"  {pad('合計', 14)} {bar(overall)} {overall:5.1f}   {VERDICT_JA[verdict]}", file=out)
    for f in flags:
        print(f"\n  致命的  {f}", file=out)
    if verdict != "STRONG":
        weakest = min(CHECKS, key=lambda c: results[c][0])
        print(f"\n  いちばん弱いのは「{LABELS[weakest]}」。そこを直してもう一度。", file=out)
    print("", file=out)


def render_table(rows, out=sys.stdout):
    print("\nフックの順位\n" + "=" * 78, file=out)
    for i, r in enumerate(rows, 1):
        mark = "->" if i == 1 else "  "
        hook = r["hook"] if len(r["hook"]) <= 34 else r["hook"][:32] + "…"
        print(f"{mark} {r['score']:5.1f} {pad(VERDICT_JA[r['verdict']], 8)} {hook}", file=out)
        print(f"        いちばん弱い: {LABELS[r['weakest']]} ({r['checks'][r['weakest']]['score']:.0f})", file=out)
        for f in r["flags"]:
            print(f"        致命的: {f}", file=out)
    print("\n1位で撮る。1位が50点未満なら、どれもまだフックになっていない。\n", file=out)


def main():
    ap = argparse.ArgumentParser(description="リールのフックを5つの性質で採点する（日本語版）。")
    ap.add_argument("input", nargs="?", default="-", help="1行に1案のファイル。- で標準入力")
    ap.add_argument("--hook", help="1案だけをその場で採点する")
    ap.add_argument("--cps", type=float, default=DEFAULT_CPS,
                    help=f"1秒に話すかなの数（初期値 {DEFAULT_CPS}）")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    if args.hook:
        lines = [args.hook]
    else:
        raw = sys.stdin.read() if args.input == "-" else open(args.input, encoding="utf-8").read()
        lines = [l.strip() for l in raw.splitlines() if l.strip()]
    if not lines:
        print("採点するフックがない", file=sys.stderr)
        sys.exit(2)

    payload = []
    for line in lines:
        results, overall, verdict, flags = run(line, args.cps)
        payload.append({
            "hook": line,
            "checks": {k: {"score": round(v[0], 1), "detail": v[1]} for k, v in results.items()},
            "weakest": min(CHECKS, key=lambda c: results[c][0]),
            "flags": flags,
            "score": round(overall, 1),
            "verdict": verdict,
        })

    if args.json:
        print(json.dumps(payload if len(payload) > 1 else payload[0], indent=2, ensure_ascii=False))
        return

    if len(payload) == 1:
        results, overall, verdict, flags = run(lines[0], args.cps)
        render_one(lines[0], results, overall, verdict, flags)
    else:
        render_table(sorted(payload, key=lambda r: -r["score"]))

    sys.exit(0 if max(p["score"] for p in payload) >= 70 else 1)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    main()
