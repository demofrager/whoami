from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
import logging
import os
from pathlib import Path

from flask import Flask, Response, abort, render_template, request
import markdown
from prometheus_client import CONTENT_TYPE_LATEST, Counter, generate_latest

BASE_DIR = Path(__file__).resolve().parent
BLOG_DIR = BASE_DIR / "blogs"
ROADMAP_DIR = BASE_DIR / "roadmap"

app = Flask(__name__)
GITHUB_URL = os.environ.get("GITHUB_URL", "https://github.com/demofrager")
LOG_IPS = os.environ.get("LOG_IPS", "true").lower() == "true"

REQUEST_COUNT = Counter(
    "whoami_http_requests_total",
    "Total HTTP requests",
    ["method", "endpoint", "http_status", "country"],
)

ip_logger = logging.getLogger("whoami.access")
if not ip_logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(message)s"))
    ip_logger.addHandler(handler)
ip_logger.setLevel(logging.INFO)


@dataclass(frozen=True)
class Post:
    slug: str
    title: str
    excerpt: str
    content_html: str
    published_at: datetime | None
    updated_at: datetime


@dataclass(frozen=True)
class RoadmapEntry:
    slug: str
    title: str
    status: str
    status_class: str
    deadline: str | None
    progress: int | None
    excerpt: str
    content_html: str
    updated_at: datetime


def _parse_markdown(md_text: str) -> tuple[str, str, str, datetime | None]:
    lines = [line.rstrip() for line in md_text.splitlines()]
    title = "Untitled"
    body_start = 0

    if lines and lines[0].startswith("# "):
        title = lines[0][2:].strip() or title
        body_start = 1

    published_at = None
    body_lines: list[str] = []
    for line in lines[body_start:]:
        if line.lower().startswith("date:"):
            date_value = line.split(":", 1)[1].strip()
            if date_value:
                try:
                    published_at = datetime.fromisoformat(date_value)
                except ValueError:
                    published_at = None
            continue
        body_lines.append(line)

    body_text = "\n".join(body_lines).strip()
    excerpt = _extract_excerpt(body_text)

    render_lines = []
    if lines and lines[0].startswith("# "):
        render_lines.append(lines[0])
    render_lines.extend(body_lines)
    html = markdown.markdown(
        "\n".join(render_lines).strip(),
        extensions=["fenced_code", "tables", "sane_lists", "nl2br"],
    )
    return title, excerpt, html, published_at


def _extract_excerpt(body_text: str) -> str:
    for paragraph in body_text.split("\n\n"):
        clean = paragraph.strip()
        if clean:
            return clean.replace("\n", " ")
    return ""


def _parse_deadline(deadline: str | None) -> datetime | None:
    if not deadline:
        return None
    for parser in (
        datetime.fromisoformat,
        lambda value: datetime.strptime(value, "%Y-%m-%d"),
        lambda value: datetime.strptime(value, "%Y/%m/%d"),
    ):
        try:
            return parser(deadline)
        except ValueError:
            continue
    return None


def _status_rank(status: str) -> int:
    return {
        "now": 0,
        "next": 1,
        "later": 2,
        "done": 3,
    }.get(status.strip().lower(), 0)


def _roadmap_sort_key(entry: RoadmapEntry) -> tuple[int, int, float, float]:
    rank = _status_rank(entry.status)
    deadline_dt = _parse_deadline(entry.deadline)
    if deadline_dt is None:
        return (rank, 1, float("inf"), -entry.updated_at.timestamp())
    distance = abs((deadline_dt - datetime.now()).total_seconds())
    return (rank, 0, distance, -entry.updated_at.timestamp())


def _homepage_sort_key(entry: RoadmapEntry) -> tuple[int, int, float]:
    progress = entry.progress if entry.progress is not None else -1
    deadline_dt = _parse_deadline(entry.deadline)
    if deadline_dt is None:
        return (-progress, 1, float("inf"))
    return (-progress, 0, deadline_dt.timestamp())


def _select_homepage_entries(entries: list[RoadmapEntry]) -> list[RoadmapEntry]:
    candidates = [
        entry
        for entry in entries
        if entry.progress is not None and entry.progress < 100
    ]
    candidates.sort(key=_homepage_sort_key)
    return candidates[:3]


def _parse_roadmap_entry(
    md_text: str,
) -> tuple[str, str, str, str | None, int | None, str]:
    lines = [line.rstrip() for line in md_text.splitlines()]
    title = "Untitled"
    body_start = 0
    if lines and lines[0].startswith("# "):
        title = lines[0][2:].strip() or title
        body_start = 1

    status = "Now"
    deadline = None
    progress = None
    body_lines: list[str] = []
    for line in lines[body_start:]:
        if line.lower().startswith("status:"):
            status_value = line.split(":", 1)[1].strip()
            if status_value:
                status = status_value
            continue
        if line.lower().startswith("deadline:"):
            deadline_value = line.split(":", 1)[1].strip()
            if deadline_value:
                deadline = deadline_value
            continue
        if line.lower().startswith("progress:"):
            progress_value = line.split(":", 1)[1].strip().rstrip("%")
            if progress_value:
                try:
                    parsed = int(progress_value)
                    if 0 <= parsed <= 100:
                        progress = parsed
                except ValueError:
                    pass
            continue
        body_lines.append(line)

    body_text = "\n".join(body_lines).strip()
    excerpt = _extract_excerpt(body_text)
    html = markdown.markdown(
        body_text,
        extensions=["fenced_code", "tables", "sane_lists", "nl2br"],
    )
    return title, status, html, deadline, progress, excerpt


def load_posts() -> list[Post]:
    BLOG_DIR.mkdir(exist_ok=True)
    posts: list[Post] = []
    for md_path in sorted(BLOG_DIR.glob("*.md")):
        md_text = md_path.read_text(encoding="utf-8")
        title, excerpt, html, published_at = _parse_markdown(md_text)
        posts.append(
            Post(
                slug=md_path.stem,
                title=title,
                excerpt=excerpt,
                content_html=html,
                published_at=published_at,
                updated_at=datetime.fromtimestamp(md_path.stat().st_mtime),
            )
        )
    posts.sort(key=lambda post: post.updated_at, reverse=True)
    return posts


def load_roadmap() -> list[RoadmapEntry]:
    ROADMAP_DIR.mkdir(exist_ok=True)
    entries: list[RoadmapEntry] = []
    for md_path in sorted(ROADMAP_DIR.glob("*.md")):
        md_text = md_path.read_text(encoding="utf-8")
        title, status, html, deadline, progress, excerpt = _parse_roadmap_entry(
            md_text
        )
        status_key = status.strip().lower()
        status_class = {
            "now": "status-now",
            "next": "status-next",
            "later": "status-later",
            "done": "status-done",
        }.get(status_key, "status-now")
        entries.append(
            RoadmapEntry(
                slug=md_path.stem,
                title=title,
                status=status or "Now",
                status_class=status_class,
                deadline=deadline,
                progress=progress,
                excerpt=excerpt,
                content_html=html,
                updated_at=datetime.fromtimestamp(md_path.stat().st_mtime),
            )
        )
    entries.sort(key=_roadmap_sort_key)
    return entries


@app.context_processor
def inject_social_links():
    return {"github_url": GITHUB_URL}


def _get_client_ip() -> str:
    forwarded_for = request.headers.get("X-Forwarded-For", "")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip.strip()
    return request.remote_addr or "unknown"


@app.after_request
def record_request_metrics(response):
    if request.endpoint == "metrics" or request.path.startswith("/static/"):
        return response
    endpoint = request.url_rule.rule if request.url_rule else "not_found"
    country = request.headers.get("CF-IPCountry") or request.headers.get(
        "X-Geo-Country"
    )
    if not country:
        country = "unknown"
    REQUEST_COUNT.labels(
        request.method,
        endpoint,
        str(response.status_code),
        country,
    ).inc()
    if LOG_IPS:
        payload = {
            "timestamp": datetime.utcnow().isoformat(timespec="seconds") + "Z",
            "ip": _get_client_ip(),
            "method": request.method,
            "path": request.path,
            "endpoint": endpoint,
            "status": response.status_code,
            "country": country,
            "user_agent": request.headers.get("User-Agent", ""),
        }
        ip_logger.info(json.dumps(payload, separators=(",", ":")))
    return response


@app.route("/")
def index():
    posts = load_posts()
    roadmap_entries = load_roadmap()
    return render_template(
        "index.html",
        posts=posts[:3],
        roadmap_entries=_select_homepage_entries(roadmap_entries),
    )


@app.route("/venting")
def venting_list():
    posts = load_posts()
    return render_template("venting_list.html", posts=posts)


@app.route("/venting/<slug>")
def venting_post(slug: str):
    posts = load_posts()
    for post in posts:
        if post.slug == slug:
            return render_template("venting_post.html", post=post)
    abort(404)


@app.route("/roadmap")
def roadmap_list():
    entries = load_roadmap()
    return render_template("roadmap_list.html", entries=entries)


@app.route("/roadmap/<slug>")
def roadmap_post(slug: str):
    entries = load_roadmap()
    for entry in entries:
        if entry.slug == slug:
            return render_template("roadmap_post.html", entry=entry)
    abort(404)


@app.route("/metrics")
def metrics():
    return Response(generate_latest(), mimetype=CONTENT_TYPE_LATEST)


if __name__ == "__main__":
    app.run(debug=True)
