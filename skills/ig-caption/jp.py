#!/usr/bin/env python3
"""
jp.py - 日本語の文を測るための小さな道具。外部のライブラリは使わない。

英語版は「単語の数」で長さや具体性を測っていた。日本語は単語の間に空白が
ないので、それでは数えられない。ここでは代わりに次の物を使う。

  yomi()      読みの長さ（かなに直した時のおおよその音の数＝モーラ）。
              かなは1、漢字は1字1.7（日本語のリール台本8本を実際の読みと
              比べて出した値・中央値1.69）、英字と数字は読み方から見積もる。
              話す秒数 = yomi() / 1秒に話すかなの数。
  width()     画面での幅。全角は2、半角は1。
  concrete()  具体的な目印（数字・金額・英字の固有名詞・「」でくくった名前）。
  sentences() 文に分ける（。！？と改行）。
  content_tokens()  ループ（最後の言葉が冒頭に戻るか）を見るための中身の語。

同じファイルが ig-reel・ig-caption・ig-human に入っている。どのフォルダも
単独で写して動くようにするため。直す時は3か所とも直す。
"""

import re
import unicodedata

KANJI_MORA = 1.7          # 漢字1字のおおよその読みの長さ（モーラ）
SMALL_KANA = set("ゃゅょぁぃぅぇぉゎャュョァィゥェォヮ")
KANJI_RE = r"[一-鿿々〆]"

# 英字の略語のうち、具体的な名前とは言えない物。「AI」は日本語のフックで
# いちばんよく出る英字だが、それだけでは何も特定しない。
GENERIC_LATIN = {
    "AI", "SNS", "OK", "NG", "DM", "PC", "URL", "PR", "vs", "VS", "IT",
    "TV", "CM", "Q", "A", "QA", "FAQ", "PDF", "HP", "ok", "ng",
}

# 数字の読み（漢数字の読みのモーラ数）
_DIGIT_MORA = {0: 0, 1: 2, 2: 1, 3: 2, 4: 2, 5: 1, 6: 2, 7: 2, 8: 2, 9: 2}
_PLACE_MORA = {1: 0, 10: 2, 100: 2, 1000: 2}           # じゅう・ひゃく・せん
_BIG_MORA = [(10 ** 8, 2), (10 ** 4, 2)]                # おく・まん

# 長い単位を先に（「万円」を「万」で止めないため）。
COUNTERS = (r"(?:万円|億円|千円|万人|万回|時間|週間|ヶ月|か月|カ月|ヵ月|種類|ステップ|"
            r"つ|個|人|名|日|年|回|本|枚|件|円|万|億|千|倍|割|%|％|分|秒|週|歳|才|位|"
            r"選|社|冊|語|字|行|点|台|杯|kg|km|GB|MB|k|K|ドル)")
NUM_RE = re.compile(r"[$¥￥]?\s?[0-9０-９][0-9０-９,，.．]*\s?" + COUNTERS + r"?")
KANJI_NUM_RE = re.compile(
    r"(?:[二三四五六七八九十百千]|[一二三四五六七八九十百千]{2,})[一二三四五六七八九十百千万億]*"
    + COUNTERS)
LATIN_NAME_RE = re.compile(r"[A-Za-z][A-Za-z0-9.+\-']*(?:\s[A-Z][A-Za-z0-9.+\-']*)*")
QUOTED_RE = re.compile(r"「([^「」\n]{2,25})」")


def _int_mora(n):
    """整数を日本語で読んだ時のおおよそのモーラ数。"""
    if n == 0:
        return 2                                      # ぜろ
    total = 0
    for big, mora in _BIG_MORA:
        if n >= big:
            total += _int_mora(n // big) + mora
            n %= big
    for place in (1000, 100, 10, 1):
        d = n // place
        n %= place
        if not d:
            continue
        if place > 1 and d == 1:
            total += _PLACE_MORA[place]               # 「いちじゅう」とは言わない
        else:
            total += _DIGIT_MORA[d] + _PLACE_MORA[place]
    return total


def num_mora(token):
    """'18,000' や '1.2' のような数字の読みの長さ。"""
    t = unicodedata.normalize("NFKC", token).replace(",", "")
    if not t:
        return 0
    if "." in t:
        head, _, tail = t.partition(".")
        head_m = _int_mora(int(head)) if head.isdigit() else 0
        return head_m + 2 + sum(_DIGIT_MORA.get(int(c), 2) or 2 for c in tail if c.isdigit())
    return _int_mora(int(t)) if t.isdigit() else 0


def _latin_mora(word):
    """英字の語の読みの長さ。略語は1文字ずつ（エー・ピー・アイ）、それ以外はカタカナ読みの見当。"""
    total = 0
    for part in re.findall(r"[A-Z]{2,}(?![a-z])|[A-Z]?[a-z]+|[A-Z]|[0-9]+", word):
        if part.isdigit():
            total += num_mora(part)
        elif part.isupper():
            total += round(len(part) * 2.2)
        else:
            total += max(2, round(len(part) * 0.8))
    return total


def yomi(text):
    """読みの長さ（モーラ）の見積もり。話す秒数の計算に使う。"""
    t = unicodedata.normalize("NFKC", text)
    total = 0.0
    for m in re.finditer(r"[0-9][0-9,.]*|[A-Za-z][A-Za-z0-9']*", t):
        tok = m.group(0)
        total += num_mora(tok) if tok[0].isdigit() else _latin_mora(tok)
    rest = re.sub(r"[0-9][0-9,.]*|[A-Za-z][A-Za-z0-9']*", "", t)
    for c in rest:
        if ("ぁ" <= c <= "ゟ" or "゠" <= c <= "ヿ") and c not in SMALL_KANA:
            total += 1                                 # ー・っ も1拍
        elif re.match(KANJI_RE, c):
            total += KANJI_MORA
        elif c in "%":
            total += 5                                 # パーセント
        elif c in "$":
            total += 2                                 # ドル
        elif c in "¥":
            total += 2                                 # えん
        elif c in "&":
            total += 3                                 # アンド
        elif c in "+":
            total += 3                                 # プラス
        elif c in "×":
            total += 3                                 # かける
    return total


def width(text):
    """画面での幅。全角2・半角1。"""
    return sum(2 if unicodedata.east_asian_width(c) in "FWA" else 1 for c in text)


def concrete(text):
    """具体的な目印の一覧。数字（単位つき）・漢数字＋助数詞・金額・英字の名前・「」の名前。"""
    found = []
    for m in NUM_RE.finditer(text):
        s = m.group(0).strip()
        if s:
            found.append(s)
    for m in KANJI_NUM_RE.finditer(text):
        found.append(m.group(0))
    for m in LATIN_NAME_RE.finditer(text):
        w = m.group(0).strip()
        if w in GENERIC_LATIN or len(w) < 2:
            continue
        if any(c.isupper() for c in w) or len(w) >= 4:
            found.append(w)
    for m in QUOTED_RE.finditer(text):
        found.append("「" + m.group(1) + "」")
    return found


def sentences(text, min_chars=4):
    """文に分ける。句点・感嘆符・疑問符・改行で切る。短すぎる切れ端は捨てる。"""
    parts = re.split(r"(?<=[。．！？!?])|\n", text)
    return [p.strip() for p in parts if len(re.sub(r"\s", "", p)) >= min_chars]


_TOKEN_RE = re.compile(r"[ァ-ヶー]{2,}|" + KANJI_RE + r"{2,}|[A-Za-z][A-Za-z0-9]+|[0-9０-９][0-9０-９,]*")
_TOKEN_STOP = {
    "自分", "今日", "今回", "動画", "本当", "実際", "結果", "全部", "時間", "方法",
    "必要", "一番", "最初", "最後", "大事", "簡単", "普通", "場合", "感じ",
}


def content_tokens(text):
    """数字（単位ごと）・カタカナ2字以上・漢字2字以上・英字の語。よく出るだけの語は除く。"""
    nums = {m.group(0).strip() for m in NUM_RE.finditer(text) if m.group(0).strip()}
    rest = NUM_RE.sub(" ", text)
    return nums | {t for t in _TOKEN_RE.findall(rest) if t not in _TOKEN_STOP}
