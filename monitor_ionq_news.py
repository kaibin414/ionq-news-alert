import html
import json
import os
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin, urlsplit, urlunsplit

import requests


NEWS_BASE_URL = "https://investors.ionq.com"
NEWS_FEED_URL = (
    "https://investors.ionq.com/feed/PressRelease.svc/GetPressReleaseList"
)
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")
TEST_MODE = os.environ.get("TEST_MODE", "false").lower() == "true"

SEEN_FILE = Path("seen_ionq_news.json")


def load_seen_ids():
    if not SEEN_FILE.exists():
        return set()

    try:
        data = json.loads(SEEN_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        print(f"Could not read seen IonQ news file: {error}")
        return set()

    if isinstance(data, list):
        return {str(item) for item in data}

    if isinstance(data, dict):
        return {str(item) for item in data.get("seen_ids", [])}

    return set()


def save_seen_ids(seen_ids):
    SEEN_FILE.write_text(
        json.dumps(sorted(seen_ids), indent=2, ensure_ascii=False) + "\n",
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
    without_tags = re.sub(r"<[^>]+>", " ", text or "")
    return re.sub(r"\s+", " ", html.unescape(without_tags)).strip()


def normalize_url(url):
    parts = urlsplit(urljoin(NEWS_BASE_URL, url))
    path = parts.path.rstrip("/") or "/"
    return urlunsplit(
        (
            parts.scheme.lower(),
            parts.netloc.lower(),
            path,
            parts.query,
            "",
        )
    )


def format_date(raw_date):
    try:
        parsed = datetime.strptime(raw_date, "%m/%d/%Y %H:%M:%S")
        return parsed.strftime("%B %d, %Y").replace(" 0", " ")
    except (TypeError, ValueError):
        return clean_text(raw_date) or "Unknown date"


def fetch_ionq_news():
    params = {
        "LanguageId": 1,
        "bodyType": 3,
        "pressReleaseDateFilter": 3,
        "categoryId": "00000000-0000-0000-0000-000000000000",
        "pageSize": 50,
        "pageNumber": 0,
        "tagList": "",
        "includeTags": "true",
        "year": -1,
        "excludeSelection": 1,
    }

    try:
        response = requests.get(
            NEWS_FEED_URL,
            params=params,
            headers={"User-Agent": "ionq-news-alert/2.0"},
            timeout=60,
        )
        response.raise_for_status()
        payload = response.json()
    except requests.RequestException as error:
        print(f"Failed to fetch IonQ news feed/API: {error}")
        return []
    except (ValueError, TypeError) as error:
        print(f"Invalid JSON from IonQ news feed/API: {error}")
        return []

    raw_items = payload.get("GetPressReleaseListResult")
    if not isinstance(raw_items, list):
        print("IonQ news feed/API response did not contain a press release list.")
        return []

    news_items = []
    seen_item_ids = set()

    for raw_item in raw_items:
        title = clean_text(raw_item.get("Headline"))
        raw_url = raw_item.get("LinkToDetailPage") or raw_item.get("LinkToUrl")
        url = normalize_url(raw_url) if raw_url else ""
        press_release_id = raw_item.get("PressReleaseId")

        if not title or not url:
            continue

        item_id = (
            f"press-release:{press_release_id}"
            if press_release_id is not None
            else url
        )

        if item_id in seen_item_ids:
            continue
        seen_item_ids.add(item_id)

        news_items.append(
            {
                "id": item_id,
                "title": title,
                "date": format_date(raw_item.get("PressReleaseDate")),
                "url": url,
                "summary": clean_text(
                    raw_item.get("ShortDescription") or raw_item.get("ShortBody")
                ),
            }
        )

    return news_items


def make_message(item):
    lines = [
        "🔔 **IonQ 官方新闻更新**",
        "",
        f"**标题：** {item['title']}",
        f"**日期：** {item['date']}",
    ]

    if item["summary"]:
        summary = item["summary"]
        if len(summary) > 600:
            summary = summary[:597].rstrip() + "..."
        lines.append(f"**摘要：** {summary}")

    lines.append(f"**链接：** {item['url']}")
    return "\n".join(lines)


def was_seen(item, seen_ids):
    return item["id"] in seen_ids or item["url"] in seen_ids


def main():
    if TEST_MODE:
        send_discord("✅ IonQ 新闻推送测试成功：Discord Webhook 可以正常接收消息。")
        print("Sent Discord test message.")
        return

    seen_ids = load_seen_ids()
    news_items = fetch_ionq_news()

    if not news_items:
        print("No IonQ news items found from feed/API.")
        return

    if not seen_ids:
        save_seen_ids({item["id"] for item in news_items})
        print(
            f"Initialized seen IonQ news with {len(news_items)} current item(s). "
            "No alerts sent."
        )
        return

    new_items = [item for item in news_items if not was_seen(item, seen_ids)]

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
