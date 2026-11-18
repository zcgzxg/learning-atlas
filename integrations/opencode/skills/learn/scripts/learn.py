#!/usr/bin/env python3
"""learn-atlas knowledge CLI.

把对话里沉淀下来的知识合并进 learning-atlas 仓库，并提交、推送。
只使用 Python 标准库；所有输出都是 JSON，方便 agent 读取。
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import fcntl
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path


CONFIG_ENV = "LEARN_ATLAS_CONFIG"
REPO_ENV = "LEARN_ATLAS_REPO"
AUTO_PUSH_ENV = "LEARN_ATLAS_AUTO_PUSH"
DEFAULT_CONFIG = Path.home() / ".config" / "opencode" / "learn-atlas.json"
DEFAULT_REPO = Path.home() / "code" / "github" / "learning-atlas"

SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
SECRET_PATTERNS = [
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"(?i)\bpassword\s*[:=]\s*\S{4,}"),
    re.compile(r"(?i)\bapi[_-]?key\s*[:=]\s*\S{8,}"),
    re.compile(r"(?i)\bsecret\s*[:=]\s*\S{8,}"),
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._-]{20,}"),
    re.compile(r"https?://[^/\s:@]+:[^/\s@]+@"),
]


class LearnError(Exception):
    pass


def today() -> str:
    return dt.date.today().isoformat()


def config_path() -> Path:
    return Path(os.environ.get(CONFIG_ENV, DEFAULT_CONFIG)).expanduser()


def load_config() -> dict:
    path = config_path()
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LearnError(f"无法读取配置文件 {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise LearnError(f"配置文件 {path} 必须是 JSON 对象")
    return value


def resolve_repo() -> Path:
    cfg = load_config()
    raw = os.environ.get(REPO_ENV) or cfg.get("repo") or str(DEFAULT_REPO)
    repo = Path(str(raw)).expanduser()
    try:
        repo = repo.resolve()
    except OSError:
        pass
    if not repo.is_dir():
        raise LearnError(
            f"知识库目录不存在：{repo}。请运行 integrations/opencode/install.sh，"
            f"或设置 {REPO_ENV} / 修改 {config_path()}"
        )
    if not (repo / "knowledge").is_dir():
        raise LearnError(f"{repo} 不像 learning-atlas 仓库：缺少 knowledge/ 目录")
    run_git(repo, ["rev-parse", "--git-dir"])
    return repo


def auto_push() -> bool:
    env = os.environ.get(AUTO_PUSH_ENV)
    if env is not None:
        return env.strip().lower() not in {"0", "false", "no", "off"}
    cfg = load_config()
    return bool(cfg.get("autoPush", True))


def run_git(
    repo: Path, args: list[str], check: bool = True
) -> subprocess.CompletedProcess:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    )
    if check and proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise LearnError(f"git {' '.join(args)} 失败：{detail}")
    return proc


def git_dir(repo: Path) -> Path:
    out = run_git(repo, ["rev-parse", "--absolute-git-dir"]).stdout.strip()
    if not out:
        raise LearnError("无法定位 .git 目录")
    return Path(out)


@contextlib.contextmanager
def repo_lock(repo: Path):
    lock = git_dir(repo) / "learn-atlas.lock"
    handle = lock.open("a+", encoding="utf-8")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        with contextlib.suppress(OSError):
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
        os.replace(tmp, path)
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp)


def parse_scalar(raw: str):
    raw = raw.strip()
    if raw == "":
        return ""
    if raw.startswith("[") or raw.startswith('"') or raw.startswith("{"):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            if raw.startswith("[") and raw.endswith("]"):
                return [
                    part.strip().strip("\"'")
                    for part in raw[1:-1].split(",")
                    if part.strip()
                ]
            return raw.strip("\"'")
    if raw.lower() in {"true", "false"}:
        return raw.lower() == "true"
    if raw.lower() in {"null", "none"}:
        return None
    return raw.strip("\"'")


def read_note(path: Path) -> tuple[dict, str, str]:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise LearnError(f"读取失败 {path}: {exc}") from exc
    raw = raw.replace("\r\n", "\n").replace("\r", "\n")
    if raw.startswith("\ufeff"):
        raw = raw[1:]
    if not raw.startswith("---\n"):
        raise LearnError(f"{path} 缺少 frontmatter（文件应以 --- 开头）")
    end = raw.find("\n---", 4)
    if end == -1:
        raise LearnError(f"{path} 的 frontmatter 没有结束标记 ---")
    header = raw[4:end]
    rest = raw[end + 4 :]
    if rest.startswith("\n"):
        rest = rest[1:]

    data: dict = {}
    for line in header.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if ":" not in stripped:
            raise LearnError(f"{path} 的 frontmatter 行无法解析：{line}")
        key, value = stripped.split(":", 1)
        key = key.strip()
        if not key:
            raise LearnError(f"{path} 的 frontmatter 存在空键：{line}")
        data[key] = parse_scalar(value)

    return data, rest, raw


def dump_note(data: dict, body: str) -> str:
    lines = ["---"]
    for key, value in data.items():
        if isinstance(value, list):
            encoded = json.dumps(value, ensure_ascii=False)
        elif isinstance(value, bool):
            encoded = "true" if value else "false"
        elif isinstance(value, (int, float)):
            encoded = str(value)
        elif value is None:
            encoded = '""'
        else:
            encoded = json.dumps(str(value), ensure_ascii=False)
        lines.append(f"{key}: {encoded}")
    lines.append("---")
    body = body.strip("\n")
    return "\n".join(lines) + "\n\n" + body + "\n"


def assert_safe(value: str, field: str) -> None:
    if not isinstance(value, str):
        raise LearnError(f"{field} 必须是字符串")
    for pattern in SECRET_PATTERNS:
        if pattern.search(value):
            raise LearnError(f"{field} 看起来包含密钥或凭据，已拒绝写入")


def clean_text(value, field: str, limit: int) -> str:
    if not isinstance(value, str):
        raise LearnError(f"{field} 必须是字符串")
    text = re.sub(r"\s+", " ", value).strip()
    if not text:
        raise LearnError(f"{field} 不能为空")
    if len(text) > limit:
        raise LearnError(f"{field} 过长（最多 {limit} 字符）")
    assert_safe(text, field)
    return text


def clean_category(value) -> str:
    if not isinstance(value, str):
        raise LearnError("category 必须是字符串")
    category = value.strip().strip("/").replace("\\", "/")
    if not category:
        raise LearnError("category 不能为空，例如 ai/llm")
    parts = category.split("/")
    if len(parts) > 4:
        raise LearnError("category 层级过深（最多 4 层）")
    for part in parts:
        if not SLUG_RE.match(part):
            raise LearnError(
                f"category 片段不合规：{part}（只允许小写字母、数字、连字符）"
            )
    return category


def clean_slug(value) -> str:
    if not isinstance(value, str):
        raise LearnError("slug 必须是字符串")
    slug = value.strip()
    if slug.endswith(".md"):
        slug = slug[:-3]
    if not SLUG_RE.match(slug):
        raise LearnError("slug 不合规：只允许小写字母、数字、连字符，例如 logits")
    if len(slug) > 80:
        raise LearnError("slug 过长（最多 80 字符）")
    return slug


def clean_tags(value) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise LearnError("tags 必须是字符串数组")
    result: list[str] = []
    for item in value:
        tag = clean_text(item, "tags", 40).lower()
        if tag not in result:
            result.append(tag)
    if len(result) > 12:
        raise LearnError("tags 最多 12 个")
    return result


def clean_points(value) -> list[str]:
    if not isinstance(value, list) or not value:
        raise LearnError("points 必须是非空字符串数组")
    if len(value) > 10:
        raise LearnError("points 最多 10 条，建议 2–4 条")
    result: list[str] = []
    for item in value:
        text = clean_text(item, "points", 400)
        text = re.sub(r"^[-*]\s+", "", text)
        if text not in result:
            result.append(text)
    return result


def clean_mechanism(value) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise LearnError("mechanism 必须是字符串数组")
    if len(value) > 8:
        raise LearnError("mechanism 最多 8 条，建议 2–4 条")
    result: list[str] = []
    for item in value:
        text = clean_text(item, "mechanism", 400)
        text = re.sub(r"^[-*]\s+", "", text)
        if text not in result:
            result.append(text)
    return result


def normalize_point(text: str) -> str:
    return "".join(ch for ch in text.lower() if ch.isalnum())


def dedupe_bullets(existing: list[str], bullets: list[str]) -> tuple[list[str], int]:
    existing_norms = [(item, normalize_point(item)) for item in existing]
    accepted: list[str] = []
    skipped = 0
    for bullet in bullets:
        norm = normalize_point(bullet)
        duplicate = False
        for _, old_norm in existing_norms:
            if norm == old_norm:
                duplicate = True
                break
            if (
                len(norm) >= 8
                and len(old_norm) >= 8
                and (norm in old_norm or old_norm in norm)
            ):
                duplicate = True
                break
        if duplicate:
            skipped += 1
            continue
        existing_norms.append((bullet, norm))
        accepted.append(bullet)
    return accepted, skipped


def merge_bullets(
    body: str,
    heading: str,
    bullets: list[str],
    before_heading: str | None = None,
    dedupe_all: bool = False,
) -> tuple[str, int, int]:
    """Merge bullets into a section, creating it if needed.

    If the section is new and ``before_heading`` exists, insert the new
    section before that heading so 概述 → 核心机制 → 要点 stays ordered.
    """
    if not bullets:
        return body, 0, 0

    lines = body.split("\n")
    heading_index = None
    for index, line in enumerate(lines):
        if line.strip() == heading:
            heading_index = index
            break

    existing: list[str] = []
    section_end = len(lines)
    if heading_index is not None:
        for index in range(heading_index + 1, len(lines)):
            if re.match(r"^##\s+", lines[index]):
                section_end = index
                break
        for line in lines[heading_index + 1 : section_end]:
            match = re.match(r"^\s*[-*]\s+(.+?)\s*$", line)
            if match:
                existing.append(match.group(1))

    if dedupe_all:
        existing = [
            match.group(1)
            for line in lines
            if (match := re.match(r"^\s*[-*]\s+(.+?)\s*$", line))
        ]

    accepted, skipped = dedupe_bullets(existing, bullets)
    if not accepted:
        return body, 0, skipped

    bullet_lines = [f"- {point}" for point in accepted]

    if heading_index is None:
        section = [heading, ""] + bullet_lines
        if before_heading:
            insert_at = next(
                (
                    index
                    for index, line in enumerate(lines)
                    if line.strip() == before_heading
                ),
                None,
            )
            if insert_at is not None:
                before = lines[:insert_at]
                after = lines[insert_at:]
                while before and before[-1].strip() == "":
                    before.pop()
                new_lines = before + [""] + section + [""] + after
                return (
                    "\n".join(new_lines).strip("\n") + "\n",
                    len(accepted),
                    skipped,
                )
        prefix = body.rstrip("\n")
        addition = "\n\n" + "\n".join(section)
        return (prefix + addition).strip("\n") + "\n", len(accepted), skipped

    before = lines[:section_end]
    after = lines[section_end:]
    while before and before[-1].strip() == "":
        before.pop()
    if before and before[-1].strip() == heading:
        new_lines = before + [""] + bullet_lines
    else:
        new_lines = before + bullet_lines
    if after:
        new_lines.append("")
        new_lines.extend(after)
    return "\n".join(new_lines).strip("\n") + "\n", len(accepted), skipped


def write_labels(repo: Path, category: str, label: str) -> bool:
    path = repo / "knowledge" / "_labels.json"
    labels: dict = {}
    if path.exists():
        try:
            current = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(current, dict):
                labels = current
        except (OSError, json.JSONDecodeError) as exc:
            raise LearnError(f"无法读取 {path}: {exc}") from exc
    if labels.get(category) == label:
        return False
    labels[category] = label
    ordered = dict(sorted(labels.items(), key=lambda item: item[0]))
    atomic_write(path, json.dumps(ordered, ensure_ascii=False, indent=2) + "\n")
    return True


def stage_and_commit(repo: Path, paths: list[Path], message: str) -> str | None:
    rels = [path.relative_to(repo).as_posix() for path in paths]
    if not rels:
        return None
    run_git(repo, ["add", "--", *rels])
    staged = run_git(repo, ["diff", "--cached", "--quiet", "--", *rels], check=False)
    if staged.returncode == 0:
        return None
    run_git(repo, ["commit", "-m", message, "--", *rels])
    return run_git(repo, ["rev-parse", "--short", "HEAD"]).stdout.strip()


def push(repo: Path) -> tuple[bool, str | None]:
    proc = run_git(repo, ["push"], check=False)
    if proc.returncode == 0:
        return True, None
    detail = (proc.stderr or proc.stdout or "").strip()

    if "no upstream" in detail.lower() or "has no upstream" in detail.lower():
        retry = run_git(repo, ["push", "-u", "origin", "HEAD"], check=False)
        if retry.returncode == 0:
            return True, None
        detail = (retry.stderr or retry.stdout or detail).strip()

    rebase = run_git(repo, ["pull", "--rebase", "--autostash"], check=False)
    if rebase.returncode != 0:
        detail = (rebase.stderr or rebase.stdout or detail).strip()
        return False, detail

    retry = run_git(repo, ["push"], check=False)
    if retry.returncode == 0:
        return True, None
    return False, (retry.stderr or retry.stdout or detail).strip()


def finish(repo: Path, result: dict, do_push: bool) -> dict:
    if do_push:
        pushed, error = push(repo)
        result["pushed"] = pushed
        if error:
            result["pushError"] = error
    else:
        result["pushed"] = False
        result["pushError"] = None
    return result


def cmd_add(repo: Path) -> dict:
    raw = sys.stdin.read().strip()
    if not raw:
        raise LearnError("add 需要从 stdin 读取 JSON")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise LearnError(f"stdin JSON 解析失败：{exc}") from exc
    if not isinstance(payload, dict):
        raise LearnError("stdin JSON 必须是对象")

    category = clean_category(payload.get("category"))
    slug = clean_slug(payload.get("slug"))
    title_raw = payload.get("title", "")
    title = clean_text(title_raw, "title", 80) if title_raw else ""
    summary_raw = payload.get("summary", payload.get("description", ""))
    summary = clean_text(summary_raw, "summary", 240) if summary_raw else ""
    tags = clean_tags(payload.get("tags"))
    points = clean_points(payload.get("points"))
    mechanism = clean_mechanism(payload.get("mechanism"))
    label_raw = payload.get("categoryLabel", payload.get("label", ""))
    label = clean_text(label_raw, "categoryLabel", 40) if label_raw else ""

    note_path = repo / "knowledge" / category / f"{slug}.md"
    knowledge_root = (repo / "knowledge").resolve()
    try:
        note_path.resolve().relative_to(knowledge_root)
    except ValueError as exc:
        raise LearnError("笔记路径越界") from exc

    with repo_lock(repo):
        label_changed = write_labels(repo, category, label) if label else False

        if note_path.exists():
            data, body, original = read_note(note_path)
            if not data.get("title") and title:
                data["title"] = title
            if not data.get("description") and summary:
                data["description"] = summary
            merged_tags = list(data.get("tags") or [])
            for tag in tags:
                if tag not in merged_tags:
                    merged_tags.append(tag)
            if merged_tags:
                data["tags"] = merged_tags
            if not data.get("updated"):
                data["updated"] = today()

            new_body, mechanism_added, mechanism_skipped = merge_bullets(
                body,
                "## 核心机制",
                mechanism,
                before_heading="## 要点",
                dedupe_all=True,
            )
            new_body, points_added, points_skipped = merge_bullets(
                new_body, "## 要点", points, dedupe_all=True
            )
            added = mechanism_added + points_added
            skipped = mechanism_skipped + points_skipped
            if added == 0:
                result = {
                    "ok": True,
                    "changed": label_changed,
                    "created": False,
                    "path": note_path.relative_to(repo).as_posix(),
                    "added": 0,
                    "mechanismAdded": 0,
                    "pointsAdded": 0,
                    "skipped": skipped,
                    "commit": None,
                }
                if label_changed:
                    commit = stage_and_commit(
                        repo,
                        [repo / "knowledge" / "_labels.json"],
                        f"learn({category}): label {label}",
                    )
                    result["commit"] = commit
                    return finish(repo, result, auto_push())
                result["pushed"] = False
                result["pushError"] = None
                return result

            data["updated"] = today()
            new_text = dump_note(data, new_body)
            if new_text == original:
                result = {
                    "ok": True,
                    "changed": label_changed,
                    "created": False,
                    "path": note_path.relative_to(repo).as_posix(),
                    "added": 0,
                    "mechanismAdded": 0,
                    "pointsAdded": 0,
                    "skipped": skipped,
                    "commit": None,
                }
                result["pushed"] = False
                result["pushError"] = None
                return result

            atomic_write(note_path, new_text)
            paths = [note_path]
            if label_changed:
                paths.append(repo / "knowledge" / "_labels.json")
            message = f"learn({category}): {data['title']} (+{added})"
            commit = stage_and_commit(repo, paths, message)
            result = {
                "ok": True,
                "changed": True,
                "created": False,
                "path": note_path.relative_to(repo).as_posix(),
                "added": added,
                "mechanismAdded": mechanism_added,
                "pointsAdded": points_added,
                "skipped": skipped,
                "commit": commit,
            }
            return finish(repo, result, auto_push())

        if not summary:
            raise LearnError("新建页面时 summary 不能为空")
        if not title:
            raise LearnError("新建页面时 title 不能为空")

        data = {
            "title": title,
            "description": summary,
            "tags": tags,
            "updated": today(),
        }
        body = "## 概述\n\n" + summary + "\n\n"
        if mechanism:
            body += (
                "## 核心机制\n\n"
                + "\n".join(f"- {point}" for point in mechanism)
                + "\n\n"
            )
        body += "## 要点\n\n" + "\n".join(f"- {point}" for point in points)
        atomic_write(note_path, dump_note(data, body))
        paths = [note_path]
        if label_changed:
            paths.append(repo / "knowledge" / "_labels.json")
        added = len(mechanism) + len(points)
        message = f"learn({category}): {title} (+{added})"
        commit = stage_and_commit(repo, paths, message)
        result = {
            "ok": True,
            "changed": True,
            "created": True,
            "path": note_path.relative_to(repo).as_posix(),
            "added": added,
            "mechanismAdded": len(mechanism),
            "pointsAdded": len(points),
            "skipped": 0,
            "commit": commit,
        }
        return finish(repo, result, auto_push())


def cmd_finalize(repo: Path, raw_path: str) -> dict:
    candidate = Path(raw_path).expanduser()
    if not candidate.is_absolute():
        candidate = repo / candidate
    candidate = candidate.resolve()
    knowledge_root = (repo / "knowledge").resolve()
    try:
        candidate.relative_to(knowledge_root)
    except ValueError as exc:
        raise LearnError("只能 finalize knowledge/ 下的笔记") from exc
    if not candidate.is_file():
        raise LearnError(f"笔记不存在：{candidate}")

    with repo_lock(repo):
        data, body, _ = read_note(candidate)
        data["updated"] = today()
        atomic_write(candidate, dump_note(data, body))
        rel = candidate.relative_to(repo).as_posix()
        dirty = run_git(repo, ["status", "--porcelain", "--", rel], check=False)
        if not dirty.stdout.strip():
            return {
                "ok": True,
                "changed": False,
                "path": rel,
                "commit": None,
                "pushed": False,
                "pushError": None,
            }
        category = candidate.parent.relative_to(knowledge_root).as_posix()
        title = str(data.get("title") or candidate.stem)
        commit = stage_and_commit(
            repo, [candidate], f"learn({category}): update {title}"
        )
        result = {
            "ok": True,
            "changed": True,
            "path": candidate.relative_to(repo).as_posix(),
            "commit": commit,
        }
        return finish(repo, result, True)


def cmd_search(repo: Path, query: str) -> dict:
    tokens = [token.lower() for token in re.split(r"\s+", query.strip()) if token]
    results = []
    for path in sorted((repo / "knowledge").rglob("*.md")):
        if path.name.startswith(("_", ".")):
            continue
        try:
            data, body, _ = read_note(path)
        except LearnError:
            continue
        title = str(data.get("title") or path.stem)
        description = str(data.get("description") or "")
        tags = data.get("tags") if isinstance(data.get("tags"), list) else []
        updated = str(data.get("updated") or "")
        haystack = f"{path.as_posix()}\n{title}\n{description}\n{' '.join(map(str, tags))}\n{body}".lower()

        score = 0
        matched = not tokens
        for token in tokens:
            if token not in haystack:
                continue
            matched = True
            if token in title.lower():
                score += 50
            if token in " ".join(map(str, tags)).lower():
                score += 25
            if token in path.as_posix().lower():
                score += 25
            if token in description.lower():
                score += 15
            score += min(body.lower().count(token), 5) * 4
        if not matched:
            continue

        snippets = []
        for line in body.splitlines():
            clean = line.strip()
            if not clean:
                continue
            if any(token in clean.lower() for token in tokens):
                snippets.append(clean[:180])
            if len(snippets) >= 3:
                break

        results.append(
            {
                "path": path.relative_to(repo).as_posix(),
                "title": title,
                "description": description,
                "tags": tags,
                "updated": updated,
                "score": score,
                "snippets": snippets,
            }
        )

    results.sort(key=lambda item: (item["score"], item["updated"]), reverse=True)
    return {"ok": True, "query": query, "results": results[:12]}


def cmd_tree(repo: Path) -> dict:
    labels_path = repo / "knowledge" / "_labels.json"
    labels = {}
    if labels_path.exists():
        with contextlib.suppress(OSError, json.JSONDecodeError):
            loaded = json.loads(labels_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                labels = loaded

    categories: dict[str, list] = {}
    for path in sorted((repo / "knowledge").rglob("*.md")):
        if path.name.startswith(("_", ".")):
            continue
        try:
            data, _, _ = read_note(path)
        except LearnError:
            continue
        category = path.parent.relative_to(repo / "knowledge").as_posix()
        if category == ".":
            category = ""
        categories.setdefault(category, []).append(
            {
                "path": path.relative_to(repo).as_posix(),
                "title": str(data.get("title") or path.stem),
                "updated": str(data.get("updated") or ""),
            }
        )

    payload = []
    for category, pages in sorted(categories.items()):
        payload.append(
            {
                "category": category,
                "label": labels.get(category, category),
                "pages": pages,
            }
        )
    return {"ok": True, "labels": labels, "categories": payload}


def split_status_line(line: str) -> tuple[str, str] | None:
    if len(line) < 4:
        return None
    status = line[:2]
    path = line[3:].strip()
    if " -> " in path:
        path = path.split(" -> ", 1)[1]
    path = path.strip().strip('"')
    return (status, path) if path else None


def section_bullets(body: str, heading: str) -> list[str]:
    lines = body.split("\n")
    start = None
    for index, line in enumerate(lines):
        if line.strip() == heading:
            start = index
            break
    if start is None:
        return []
    result: list[str] = []
    for line in lines[start + 1 :]:
        if re.match(r"^##\s+", line):
            break
        match = re.match(r"^\s*[-*]\s+(.+?)\s*$", line)
        if match:
            result.append(match.group(1))
    return result


def note_preview(path: Path) -> tuple[str, list[str]]:
    try:
        data, body, _ = read_note(path)
    except LearnError:
        return "", []
    title = str(data.get("title") or "")
    preview: list[str] = []
    for heading in ("## 核心机制", "## 要点"):
        bullets = section_bullets(body, heading)
        if bullets:
            preview.append(heading)
            preview.extend(bullets)
    if not preview:
        for line in body.splitlines():
            clean = line.strip()
            if clean and not clean.startswith("#"):
                preview.append(clean)
            if len(preview) >= 8:
                break
    return title, preview[:10]


def file_preview(path: Path) -> list[str]:
    if not path.is_file():
        return []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    return [line.strip() for line in lines if line.strip()][:8]


def diff_preview(repo: Path, path: str) -> tuple[list[str], list[str], bool]:
    proc = run_git(repo, ["diff", "HEAD", "--unified=0", "--", path], check=False)
    added: list[str] = []
    removed: list[str] = []
    for line in proc.stdout.splitlines():
        if line.startswith(("+++", "---")):
            continue
        if line.startswith("+"):
            text = line[1:].strip()
            text = re.sub(r"^[-*]\s+", "", text)
            if text and not text.startswith("updated:"):
                added.append(text)
        elif line.startswith("-"):
            text = line[1:].strip()
            text = re.sub(r"^[-*]\s+", "", text)
            if text and not text.startswith("updated:"):
                removed.append(text)
    return added[:8], removed[:8], len(added) > 8 or len(removed) > 8


def status_label(status: str) -> str:
    code = status.strip()
    if code in {"??", "A", "AM"}:
        return "新增"
    if "D" in code:
        return "删除"
    if "R" in code:
        return "重命名"
    return "修改"


def pending_files(repo: Path, dirty_lines: list[str]) -> list[dict]:
    pending = []
    for line in dirty_lines:
        parsed = split_status_line(line)
        if parsed is None:
            continue
        status, rel = parsed
        candidate = repo / rel
        label = status_label(status)
        is_new = status.strip() in {"??", "A", "AM"}
        title = ""
        added: list[str] = []
        removed: list[str] = []
        truncated = False
        if candidate.suffix == ".md" and candidate.is_file():
            title, preview = note_preview(candidate)
            if is_new:
                added = preview
            else:
                added, removed, truncated = diff_preview(repo, rel)
                if not added and not removed:
                    added = preview
        elif is_new:
            added = file_preview(candidate)
        else:
            added, removed, truncated = diff_preview(repo, rel)
            if not added and not removed:
                added = file_preview(candidate)
        pending.append(
            {
                "path": rel,
                "title": title,
                "status": status,
                "statusLabel": label,
                "added": added,
                "removed": removed,
                "truncated": truncated,
            }
        )
    return pending


def unpushed_commits(repo: Path, upstream: str | None) -> list[dict]:
    if not upstream:
        return []
    proc = run_git(
        repo,
        [
            "log",
            "--format=@@%h%x09%s",
            "--name-only",
            f"{upstream}..HEAD",
            "--",
            "knowledge",
        ],
        check=False,
    )
    commits: list[dict] = []
    current: dict | None = None
    for line in proc.stdout.splitlines():
        if line.startswith("@@"):
            if current is not None:
                commits.append(current)
            meta = line[2:].split("\t", 1)
            current = {
                "hash": meta[0],
                "subject": meta[1] if len(meta) > 1 else "",
                "files": [],
            }
        elif line.strip() and current is not None:
            current["files"].append(line.strip())
    if current is not None:
        commits.append(current)
    for commit in commits:
        if len(commit["files"]) > 8:
            commit["files"] = commit["files"][:8]
            commit["filesTruncated"] = True
        else:
            commit["filesTruncated"] = False
    return commits[:10]


def cmd_status(repo: Path) -> dict:
    branch = run_git(repo, ["rev-parse", "--abbrev-ref", "HEAD"]).stdout.strip()
    dirty_raw = run_git(
        repo, ["status", "--porcelain", "--", "knowledge"]
    ).stdout.rstrip("\n")
    dirty_lines = [line for line in dirty_raw.splitlines() if line.strip()]
    upstream = run_git(
        repo, ["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"], check=False
    )
    upstream_name = upstream.stdout.strip() if upstream.returncode == 0 else None
    unpushed = None
    if upstream_name:
        count = run_git(repo, ["rev-list", "--count", "@{u}..HEAD"], check=False)
        if count.returncode == 0 and count.stdout.strip().isdigit():
            unpushed = int(count.stdout.strip())
    recent_raw = run_git(
        repo, ["log", "-5", "--format=%h %s", "--", "knowledge"], check=False
    ).stdout.strip()
    pending = pending_files(repo, dirty_lines)
    commits = unpushed_commits(repo, upstream_name)
    return {
        "ok": True,
        "repo": str(repo),
        "branch": branch,
        "upstream": upstream_name,
        "dirty": dirty_lines,
        "pending": pending,
        "unpushed": unpushed,
        "unpushedCommits": commits,
        "publishable": {"files": len(pending), "commits": len(commits)},
        "recent": [line for line in recent_raw.splitlines() if line.strip()],
    }


def cmd_publish(repo: Path) -> dict:
    with repo_lock(repo):
        dirty = run_git(
            repo, ["status", "--porcelain", "--", "knowledge"]
        ).stdout.strip()
        commit = None
        if dirty:
            run_git(repo, ["add", "--", "knowledge"])
            staged = run_git(
                repo, ["diff", "--cached", "--quiet", "--", "knowledge"], check=False
            )
            if staged.returncode != 0:
                run_git(
                    repo,
                    ["commit", "-m", "learn: publish pending notes", "--", "knowledge"],
                )
                commit = run_git(repo, ["rev-parse", "--short", "HEAD"]).stdout.strip()
        result = {"ok": True, "changed": bool(dirty), "commit": commit}
        return finish(repo, result, True)


def run(args) -> dict:
    repo = resolve_repo()
    if args.command == "add":
        return cmd_add(repo)
    if args.command == "finalize":
        return cmd_finalize(repo, args.path)
    if args.command == "search":
        return cmd_search(repo, args.query or "")
    if args.command == "tree":
        return cmd_tree(repo)
    if args.command == "status":
        return cmd_status(repo)
    if args.command == "publish":
        return cmd_publish(repo)
    raise LearnError(f"未知命令：{args.command}")


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="learn.py", description="learn-atlas 知识库 CLI"
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("add", help="从 stdin 读取 JSON 并合并一条笔记")
    finalize = sub.add_parser("finalize", help="手动修改后更新日期并提交")
    finalize.add_argument("path")
    search = sub.add_parser("search", help="搜索知识库")
    search.add_argument("query", nargs="?", default="")
    sub.add_parser("tree", help="列出知识树")
    sub.add_parser("status", help="查看仓库状态")
    sub.add_parser("publish", help="提交并推送 pending 笔记")
    args = parser.parse_args()

    try:
        result = run(args)
    except LearnError as exc:
        print(
            json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False),
            file=sys.stderr,
        )
        return 1
    except KeyboardInterrupt:
        return 130
    except Exception as exc:  # noqa: BLE001
        if os.environ.get("LEARN_ATLAS_DEBUG"):
            raise
        print(
            json.dumps(
                {"ok": False, "error": f"{type(exc).__name__}: {exc}"},
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 1

    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
