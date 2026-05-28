import json
import os
import re
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup


NEWS_URL = "https://investors.ionq.com/news/default.aspx"
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")
TEST_MODE = os.environ.get("TEST_MODE", "false").lower() == "true"

SEEN_FILE = Path("seen_ionq_news.json")


def load_seen_ids():
    if not SEEN_FILE.exists():
        return set()

    try:
        data = json.loads(SEEN_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return set()

    if isinstance(data, list):
        return set(data)

    if isinstance(data, dict):
        return set(data.get("seen_ids", []))

    return set()


def save_seen_ids(seen_ids):
    SEEN_FILE.write_text(
        json.dumps(sorted(seen_ids), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def send_discord(message):
    if not DISCORD_WEBHOOK_URL:
        raise RuntimeError("Missing DISCORD_WEBHOOK_URL")

    response = requests.post(
        DISCORD_WEBHOOK_URL,
        json={"content": message},
        timeout=30,
    )
    response.raise_for_status()


def clean_text(text):
    return re.sub(r"\s+", " ", text or "").strip()


def fetch_ionq_news():
    response = requests.get(
        NEWS_URL,
        headers={
            "User-Agent": "Mozilla/5.0 ionq-news-alert",
        },
        timeout=30,
    )
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")
    news_items = []

    for link in soup.find_all("a", href=True):
        title = clean_text(link.get_text(" "))

        if not title:
            continue

        href = link["href"]
        full_url = urljoin(NEWS_URL, href)

        lower_title = title.lower()
        lower_href = href.lower()

        looks_like_news = (
            "news" in lower_href
            or "press-release" in lower_href
            or "ionq" in lower_title
        )

        if not looks_like_news:
            continue

        if len(title) < 12:
            continue

        parent_text = clean_text(link.find_parent().get_text(" ") if link.find_parent() else "")
        date_match = re.search(
            r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},\s+\d{4}",
            parent_text,
        )
        date = date_match.group(0) if date_match else "Unknown date"

        item_id = full_url

        news_items.append(
            {
                "id": item_id,
                "title": title,
                "date": date,
                "url": full_url,
            }
        )

    unique_items = []
    seen_urls = set()

    for item in news_items:
        if item["url"] in seen_urls:
            continue
        seen_urls.add(item["url"])
        unique_items.append(item)

    return unique_items[:20]


def make_message(item):
    return (
        "🔔 **IonQ 官方新闻更新**\n\n"
        f"**标题：** {item['title']}\n"
        f"**日期：** {item['date']}\n"
        f"**链接：** {item['url']}"
    )


def main():
    if TEST_MODE:
        send_discord("✅ IonQ 新闻推送测试成功：Discord Webhook 可以正常接收消息。")
        print("Sent Discord test message.")
        return

    seen_ids = load_seen_ids()
    news_items = fetch_ionq_news()

    if not news_items:
        print("No IonQ news items found.")
        return

    new_items = [item for item in news_items if item["id"] not in seen_ids]

    if not new_items:
        print("No new IonQ news found.")
        return

    for item in reversed(new_items):
        send_discord(make_message(item))
        seen_ids.add(item["id"])
        print(f"Sent IonQ news alert: {item['title']}")

    save_seen_ids(seen_ids)
    print(f"Sent {len(new_items)} IonQ news alert(s).")


if __name__ == "__main__":
    main()
