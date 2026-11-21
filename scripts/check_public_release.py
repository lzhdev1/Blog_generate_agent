"""Smoke-test the URLs a browser uses behind the production reverse proxy."""

import json
import sys
import time
from html.parser import HTMLParser
from urllib.parse import urljoin
from urllib.request import Request, urlopen


class EntryAssets(HTMLParser):
    def __init__(self):
        super().__init__()
        self.scripts = []
        self.styles = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "script" and attrs.get("type") == "module" and attrs.get("src"):
            self.scripts.append(attrs["src"])
        if tag == "link" and "stylesheet" in attrs.get("rel", "").split() and attrs.get("href"):
            self.styles.append(attrs["href"])


def fetch(url, types):
    request = Request(url, headers={"User-Agent": "Blog-agent-release-smoke/1.0"})
    with urlopen(request, timeout=15) as response:
        mime = response.headers.get_content_type()
        if response.status != 200 or mime not in types:
            raise ValueError(f"{url} returned HTTP {response.status}, {mime}")
        return response.read()


def verify(base):
    assets = EntryAssets()
    assets.feed(fetch(base, {"text/html"}).decode("utf-8"))
    if not assets.scripts or not assets.styles:
        raise ValueError("Homepage is missing its application script or stylesheet")
    for paths, types in ((assets.scripts, {"application/javascript", "text/javascript"}),
                         (assets.styles, {"text/css"})):
        for path in paths:
            url = urljoin(base, path)
            if not url.startswith(base) or not fetch(url, types):
                raise ValueError(f"Invalid release asset: {url}")
    ready = json.loads(fetch(urljoin(base, "api/v1/ready"), {"application/json"}))
    if ready.get("status") != "ready":
        raise ValueError("Production API is not ready")


if __name__ == "__main__":
    base = sys.argv[1].rstrip("/") + "/"
    for attempt in range(3):
        try:
            verify(base)
            print(f"Verified homepage, JavaScript, CSS and API at {base}")
            break
        except (OSError, ValueError) as exc:
            if attempt == 2:
                raise
            print(f"Public check failed, retrying: {exc}", flush=True)
            time.sleep(5)
