#!/usr/bin/env python3
"""Collect Japanese news, generate X thread drafts, and post them to Discord."""

from __future__ import annotations

import argparse
import datetime as dt
import email.utils
import html
import json
import os
import textwrap
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass


GOOGLE_NEWS_RSS = "https://news.google.com/rss/search"
JST = dt.timezone(dt.timedelta(hours=9), "JST")

QUERY_GROUPS = {
    "経済": [
        "日本 経済 ニュース 物価 為替 株価 決算 when:1d",
        "日本 企業 決算 値上げ 金融 政策 ニュース when:1d",
    ],
    "エンタメ": [
        "日本 エンタメ 芸能 映画 音楽 発表 ニュース when:1d",
        "俳優 歌手 ドラマ 映画 話題 ニュース 日本 when:1d",
    ],
    "事件・犯罪": [
        "日本 事件 逮捕 詐欺 容疑者 ニュース when:1d",
        "日本 犯罪 警察 逮捕 送検 ニュース when:1d",
    ],
}

EXCLUDED_TITLE_PARTS = [
    "株価・株式情報",
    "為替レート・相場",
    "基準価格・投資信託情報",
    "プロ野球",
    "ラグビー",
    "サッカー",
    "天皇杯",
    "競馬",
]

EXCLUDED_SOURCES = {
    "Yahoo!ファイナンス",
}


@dataclass(frozen=True)
class NewsItem:
    category: str
    title: str
    url: str
    source: str
    published: str


def fetch_url(url: str, *, data: bytes | None = None, headers: dict[str, str] | None = None) -> bytes:
    request = urllib.request.Request(
        url,
        data=data,
        headers={
            "User-Agent": "morning-news-psychology-drafts/1.0",
            **(headers or {}),
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read()


def google_news_url(query: str) -> str:
    params = {
        "q": query,
        "hl": "ja",
        "gl": "JP",
        "ceid": "JP:ja",
    }
    return f"{GOOGLE_NEWS_RSS}?{urllib.parse.urlencode(params)}"


def clean_title(title: str) -> str:
    return " ".join(html.unescape(title).split())


def parse_source(item: ET.Element) -> str:
    source = item.find("source")
    if source is None or not source.text:
        return ""
    return clean_title(source.text)


def parse_published(item: ET.Element) -> str:
    text = item.findtext("pubDate") or ""
    if not text:
        return ""
    try:
        parsed = email.utils.parsedate_to_datetime(text)
        return parsed.astimezone(JST).strftime("%Y-%m-%d %H:%M")
    except (TypeError, ValueError):
        return text


def should_skip(title: str, source: str) -> bool:
    if source in EXCLUDED_SOURCES:
        return True
    return any(part in title for part in EXCLUDED_TITLE_PARTS)


def collect_news(limit: int) -> list[NewsItem]:
    seen: set[str] = set()
    items: list[NewsItem] = []
    per_category_target = max(4, (limit + len(QUERY_GROUPS) - 1) // len(QUERY_GROUPS) + 1)

    for category, queries in QUERY_GROUPS.items():
        category_items: list[NewsItem] = []
        for query in queries:
            rss = fetch_url(google_news_url(query))
            root = ET.fromstring(rss)
            for entry in root.findall("./channel/item"):
                title = clean_title(entry.findtext("title") or "")
                url = entry.findtext("link") or ""
                if not title or not url:
                    continue
                normalized = title.split(" - ")[0].strip()
                source = parse_source(entry)
                if should_skip(normalized, source):
                    continue
                key = normalized.casefold()
                if key in seen:
                    continue
                seen.add(key)
                category_items.append(
                    NewsItem(
                        category=category,
                        title=normalized,
                        url=url,
                        source=source,
                        published=parse_published(entry),
                    )
                )
                if len(category_items) >= per_category_target:
                    break
            if len(category_items) >= per_category_target:
                break
        items.extend(category_items)

    return items


def build_prompt(items: list[NewsItem], limit: int) -> str:
    today = dt.datetime.now(JST).strftime("%Y-%m-%d")
    news_lines = "\n".join(
        f"{idx}. [{item.category}] {item.title} / {item.source} / {item.published} / {item.url}"
        for idx, item in enumerate(items, 1)
    )
    return textwrap.dedent(
        f"""
        今日の日付は{today}です。以下の日本向けニュース候補から、Xで話題化しやすく、ニュース記事として確認できるものを{limit}件選んでください。

        優先カテゴリ:
        - 経済
        - エンタメ
        - 事件・犯罪

        出力形式:
        【朝のニュース心理X投稿案】YYYY-MM-DD

        1. カテゴリ｜ニュースタイトル
        記事: URL
        ① 120字前後。ニュース要点を濃く書き、読者が反応する感情（不安、驚き、共感、損失回避、違和感など）を入れる。末尾は「理由は↓」または「原因は↓」
        ② 120字前後。心理学・行動心理学の概念名を1つ入れ、今回のニュースでどう働くかを具体的に説明する。
        ③ 120字前後。読者が実際に使える見方や行動指針を書く。

        ルール:
        - 記事URLは必ず残す
        - 事件・犯罪では憶測、断定、個人攻撃、過度な煽りを避ける
        - 「心理学的に見ると」だけで終わらせず、具体的な心の動きを書く
        - Discordで読みやすいように簡潔に

        ニュース候補:
        {news_lines}
        """
    ).strip()


def generate_with_openai(prompt: str) -> str:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return fallback_message(prompt)

    model = os.environ.get("OPENAI_MODEL", "gpt-5.2")
    payload = {
        "model": model,
        "input": prompt,
        "instructions": "あなたは心理学と行動心理学に詳しい日本語SNS編集者です。ニュース事実を尊重し、短く濃いXスレッド案を作ります。",
    }
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    response = fetch_url(
        "https://api.openai.com/v1/responses",
        data=data,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )
    parsed = json.loads(response.decode("utf-8"))
    text = parsed.get("output_text")
    if text:
        return text.strip()

    chunks: list[str] = []
    for output in parsed.get("output", []):
        for content in output.get("content", []):
            if content.get("type") in {"output_text", "text"} and content.get("text"):
                chunks.append(content["text"])
    return "\n".join(chunks).strip()


def fallback_message(prompt: str) -> str:
    return (
        "OPENAI_API_KEY が未設定のため、AI生成は実行されませんでした。\n"
        "GitHub Secretsに OPENAI_API_KEY を追加すると、以下の候補から投稿案を生成します。\n\n"
        + prompt
    )


def post_to_discord(content: str, *, dry_run: bool) -> None:
    if dry_run:
        print(content)
        return

    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        raise RuntimeError("DISCORD_WEBHOOK_URL is not set.")

    chunks = split_discord_message(content)
    for index, chunk in enumerate(chunks, 1):
        payload = {"content": chunk}
        if len(chunks) > 1:
            payload["content"] = f"{chunk}\n\n({index}/{len(chunks)})"
        fetch_url(
            webhook_url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )


def split_discord_message(content: str, limit: int = 1900) -> list[str]:
    if len(content) <= limit:
        return [content]

    chunks: list[str] = []
    current = ""
    for block in content.split("\n\n"):
        addition = block if not current else f"\n\n{block}"
        if len(current) + len(addition) > limit:
            if current:
                chunks.append(current)
            current = block
        else:
            current += addition
    if current:
        chunks.append(current)
    return chunks


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Print instead of posting to Discord.")
    args = parser.parse_args()

    limit = int(os.environ.get("NEWS_ITEM_COUNT", "10"))
    candidates = collect_news(limit)
    if not candidates:
        raise RuntimeError("No news candidates found.")

    prompt = build_prompt(candidates, limit)
    content = generate_with_openai(prompt)
    post_to_discord(content, dry_run=args.dry_run)


if __name__ == "__main__":
    try:
        main()
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"HTTP error {exc.code}: {body}") from exc
