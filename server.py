# /// script
# requires-python = ">=3.12"
# dependencies = ["mcp>=2.3.0"]
# ///
"""MCP-сервер KediMeet: агенты ищут по встречам и читают их — только чтение, ничего не меняет.

    uv run --directory <kedimeet>/mcp server.py [папка встреч]
    uv run --script <KediMeet.app>/Contents/Resources/mcp/server.py [папка встреч]   # из DMG: окружение — в кэше uv
    uvx kedimeet-mcp [папка встреч]   # открытый пакет с PyPI (Kedicode-TR/kedimeet-mcp): этот же файл

Папка по умолчанию — библиотека KediMeet на этом маке. Встреча — папка с meta.json (её пишет приложение) и выхлопом
движка: segments.json, summary.json, meeting.md. Имена и названия собираются так же, как в приложении (Library.swift).
"""

import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Annotated
from urllib.parse import urlparse

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import Icon, ToolAnnotations
from pydantic import Field

__version__ = "1.0.2"  # версия пакета kedimeet-mcp на PyPI; та же — в server.json для реестра MCP (тест сверяет)

LIBRARY = Path(sys.argv[1]).expanduser() if len(sys.argv) > 1 else Path.home() / "Library/Application Support/KediMeet"

# Агент видит это при каждом разговоре — отсюда он и знает, что за рабочими вопросами надо идти сюда, без напоминаний
server = MCPServer(
    "KediMeet",
    version=__version__,
    website_url="https://kedimeet.app/ai",
    # Значок приложения с сайта: клиенты MCP показывают его рядом с именем сервера; те же адреса — в server.json
    icons=[Icon(src="https://kedimeet.app/assets/icon-180.png", mime_type="image/png", sizes=["180x180"]),
           Icon(src="https://kedimeet.app/assets/icon-64.png", mime_type="image/png", sizes=["64x64"])],
    instructions=(
        "KediMeet holds the user's recorded calls, meetings and voice notes: transcripts by speaker and summaries (decisions, tasks, "
        "open questions). When a question is about what was discussed, decided or agreed, who assigned or promised "
        "what, deadlines, the status of tasks and projects, or colleagues and their positions — look here first "
        "(search), then answer. In the answer, name the meeting and its date, and for quotes give the time in the "
        "recording."
    ),
)
# Только чтение: клиенты (Claude и другие) показывают такие инструменты отдельно и могут разрешать их без вопроса.
# Ничего не меняет, ничего не удаляет, никуда не ходит — читает папку встреч на этом маке
READ = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
DAY = Annotated[str | None, Field(description="Date YYYY-MM-DD, inclusive; empty — no bound")]


class Meeting:
    def __init__(self, folder: Path):
        self.id = folder.name
        self.folder = folder
        self.meta = json.loads((folder / "meta.json").read_text())
        self.names: dict[str, str] = self.meta.get("names") or {}
        self.summary = load(folder / "summary.json") or {}
        self.done = (folder / "meeting.md").exists()  # движок пишет его последним
        # Монолог — голосовые заметки одного человека; без kind (или с любым другим) — разговор
        self.monologue = self.meta.get("kind") == "monologue"
        # Дата встречи: recordedAt (приложение или внешний спутник) → дата в имени записи → addedAt
        recorded = self.meta.get("recordedAt")
        self.date = ((datetime.fromisoformat(recorded).astimezone() if recorded else None)
                     or recorded_at(Path(self.meta["source"]).stem) or datetime.fromisoformat(self.meta["addedAt"]).astimezone())

    def title(self, rooms: dict[str, str]) -> str:
        # Как в приложении: своё имя встречи → имя по ссылке созвона → название из резюме → имя файла
        link = self.meta.get("link")
        return (self.meta.get("title") or (rooms.get(room(link)) if link else None)
                or self.summary.get("title") or Path(self.meta["source"]).stem)

    def name(self, label: str | None) -> str:
        return self.names.get(label, label) if label else "?"

    def named(self, text: str) -> str:
        """Резюме написано до переименования — метки SPEAKER_XX меняем на имена."""
        for label, name in self.names.items():
            text = text.replace(label, name)
        return text

    def turns(self) -> list[dict]:
        """Реплики — подряд идущие фразы одного спикера, как на экране встречи. Пустые — след правки, пропускаем."""
        turns: list[dict] = []
        for s in load(self.folder / "segments.json") or []:
            text = s["text"].strip()
            if turns and turns[-1]["speaker"] == s.get("speaker"):
                turns[-1]["text"] = f'{turns[-1]["text"]} {text}'.strip()
                turns[-1]["end"] = s["end"]
            else:
                turns.append({"speaker": s.get("speaker"), "start": s["start"], "end": s["end"], "text": text})
        return [t for t in turns if t["text"]]

    def header(self, rooms: dict[str, str]) -> str:
        status = "" if self.done else " · no summary yet"  # в очереди, обрабатывается или упала — отсюда не видно
        return f"{self.title(rooms)} — {self.date:%Y-%m-%d %H:%M} [id: {self.id}]{status}"


def load(path: Path):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def recorded_at(name: str) -> datetime | None:
    """«Созвон 03.11.2026 10-59-37» или «Call 2026-11-03 10-59-37» (имя записи зависит от языка приложения) →
    дата и время записи; так же, как Meeting.recordedAt в приложении."""
    if m := re.search(r"(\d{2})\.(\d{2})\.(\d{4})(?:\D{1,3}(\d{2})[:.\-](\d{2}))?", name):
        day, month, year, hour, minute = m.groups()
    elif m := re.search(r"(\d{4})-(\d{2})-(\d{2})(?:\D{1,3}(\d{2})[:.\-](\d{2}))?", name):
        year, month, day, hour, minute = m.groups()
    else:
        return None
    try:
        return datetime(int(year), int(month), int(day), int(hour or 0), int(minute or 0)).astimezone()
    except ValueError:
        return None


def room(link: str) -> str | None:
    """«https://telemost.yandex.ru/j/307?source=calendar» → «telemost.yandex.ru/j/307» — ключ в rooms.json."""
    url = urlparse(link)
    path = url.path.strip("/")
    return f"{url.hostname}/{path}" if url.hostname and path else None


def clock(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 3600}:{s // 60 % 60:02}:{s % 60:02}" if s >= 3600 else f"{s // 60}:{s % 60:02}"


def seconds(at: str) -> float:
    """«1:02:03», «12:30» или «750» → секунды."""
    total = 0.0
    for part in at.strip().split(":"):
        total = total * 60 + float(part)
    return total


def library(since: str | None = None, until: str | None = None) -> tuple[list[Meeting], dict[str, str]]:
    """Встречи за период — новые сверху — и имена комнат. Читаем с диска каждый раз: папку меняют приложение и синк."""
    meetings = []
    for folder in LIBRARY.iterdir() if LIBRARY.is_dir() else []:
        if not (folder / "meta.json").exists():
            continue
        try:
            meeting = Meeting(folder)
        except (OSError, ValueError, KeyError):
            continue  # битый meta.json — приложение такую встречу тоже не покажет
        day = f"{meeting.date:%Y-%m-%d}"
        if (since and day < since) or (until and day > until):
            continue
        meetings.append(meeting)
    meetings.sort(key=lambda m: m.date, reverse=True)
    return meetings, load(LIBRARY / "rooms.json") or {}


def find(meeting_id: str) -> tuple[Meeting, dict[str, str]]:
    meetings, rooms = library()
    for meeting in meetings:
        if meeting.id == meeting_id:
            return meeting, rooms
    raise ToolError(f"No meeting “{meeting_id}”: take the id from search or list_meetings")  # ToolError агент видит, прочие — нет


def stems(query: str) -> list[str]:
    # ponytail: «основа» — слово без двух последних букв (не короче 4): «тарифы» найдёт «тарифах». Морфология — если мало
    words = {w for w in re.findall(r"\w+", query.lower()) if len(w) > 1}
    return sorted(w[:max(4, len(w) - 2)] if len(w) > 4 else w for w in words)


def snippet(text: str, stem: str, width: int = 320) -> str:
    at = max(text.lower().find(stem), 0)
    start = max(at - width // 3, 0)
    return ("…" if start else "") + text[start:start + width].strip() + ("…" if start + width < len(text) else "")


@server.tool(title="Search meetings", annotations=READ)
def search(
    query: Annotated[str, Field(description="Keywords in the language of the meetings themselves, as they were said "
                                            "on the call: topic, name, project")],
    since: DAY = None,
    until: DAY = None,
    limit: Annotated[int, Field(description="How many matches to return")] = 20,
) -> str:
    """Search the user's work calls: transcripts (who said what) and summaries (decisions, tasks, open questions).

    Use it first when a question is about what was discussed, decided or agreed, who assigned or promised what,
    deadlines, the status of tasks and projects, or colleagues. People ask things like "What did we decide about
    pricing?", "What did Maya promise to send me?", "When did we last talk about the API migration?", "Did anyone
    push back on the Thursday release?" Matches words with different endings. Ranked by how many query words
    matched, then newest first. Then read what you found with get_meeting and get_transcript. Read-only."""
    wanted = stems(query)
    if not wanted:
        return "Empty query: give some words to search for"
    meetings, rooms = library(since, until)
    hits = []  # (сколько слов совпало, порядок встречи, строка)
    for order, meeting in enumerate(meetings):
        units = [(f"summary, {part}", meeting.named(item))
                 for key, part in [("short", "short"), ("decisions", "decisions"), ("open_questions", "open questions")]
                 for item in meeting.summary.get(key) or []]
        units += [("summary, tasks", meeting.named((f'{t["who"]}: ' if t["who"] else "") + t["what"] + (f' (due {t["due"]})' if t.get("due") else "")))
                  for t in meeting.summary.get("tasks") or []]
        units += [(f"{clock(t['start'])}, {meeting.name(t['speaker'])}", f"{meeting.name(t['speaker'])}: {t['text']}")
                  for t in meeting.turns()]
        for where, text in units:
            lower = text.lower()
            matched = [s for s in wanted if s in lower]
            if matched:
                hits.append((len(matched), order, f"{meeting.header(rooms)}\n  {where}: {snippet(text, matched[0])}"))
    if not hits:
        return f"Nothing for “{query}”: try other words or a wider period"
    hits.sort(key=lambda h: (-h[0], h[1]))
    return f"Matches: {len(hits)}, showing the first {min(limit, len(hits))}\n\n" + "\n\n".join(h[2] for h in hits[:limit])


@server.tool(title="List meetings", annotations=READ)
def list_meetings(
    since: DAY = None,
    until: DAY = None,
    limit: Annotated[int, Field(description="How many meetings to return, newest first")] = 30,
) -> str:
    """Meetings in a period, newest first: title, date, participants and the main point of the summary. For questions
    like "What calls did I have this week?", "Catch me up on yesterday's meetings", "When did I last talk to
    Daniel?" Read-only."""
    meetings, rooms = library(since, until)
    if not meetings:
        return "No meetings in this period"
    lines = []
    for meeting in meetings[:limit]:
        people = sorted({meeting.name(t["speaker"]) for t in meeting.turns() if t["speaker"]})
        short = (meeting.summary.get("short") or [""])[0]
        who = "monologue" if meeting.monologue else f"participants: {', '.join(people) or '—'}"
        lines.append(f"{meeting.header(rooms)}\n  {who}\n  {meeting.named(short)}".rstrip())
    return "\n\n".join(lines)


@server.tool(title="Read a meeting summary", annotations=READ)
def get_meeting(meeting: Annotated[str, Field(description="Meeting id from search or list_meetings")]) -> str:
    """The full summary of a meeting: the short version, decisions, tasks (marked done or not), open questions,
    participants and how much each of them spoke, the call link, and the notes the user wrote for the meeting.
    For "What are my action items from the Northwind call?", "Write a follow-up email after today's sync",
    "Which tasks from Monday are still open?" Read-only."""
    m, rooms = find(meeting)
    turns = m.turns()
    talk: dict[str, float] = {}
    for t in turns:
        if t["speaker"]:
            talk[t["speaker"]] = talk.get(t["speaker"], 0) + t["end"] - t["start"]
    total = sum(talk.values()) or 1
    guesses = {g["label"]: g["name"] for g in m.summary.get("speakers") or [] if g.get("name")}

    def who(label: str) -> str:
        guess = f" (probably {guesses[label]})" if label not in m.names and label in guesses else ""
        return f"{m.name(label)}{guess} — {talk[label] / total:.0%}"

    done = set(m.meta.get("doneTasks") or [])
    tasks = [("[x] " if t["what"] in done else "[ ] ") + (f'{t["who"]}: ' if t["who"] else "") + t["what"] + (f' (due {t["due"]})' if t.get("due") else "")
             for t in m.summary.get("tasks") or []]
    parts = [m.header(rooms)]
    if m.meta.get("link"):
        parts.append(f"Link: {m.meta['link']}")
    if turns:
        parts.append(f"Duration: {clock(turns[-1]['end'])}")
    if m.monologue:
        parts.append("Kind: monologue — voice notes of one person")
    else:
        parts.append("Participants: " + ", ".join(who(label) for label in sorted(talk, key=talk.get, reverse=True)))
    for title, items in [("Short", m.summary.get("short")), ("Decisions", m.summary.get("decisions")),
                         ("Tasks", tasks), ("Open questions", m.summary.get("open_questions"))]:
        if items:
            parts.append(f"## {title}\n" + "\n".join(f"- {m.named(item)}" for item in items))
    if not m.summary:
        parts.append("No summary: the meeting is still being processed or summaries are off; read get_transcript")
    # Свои заметки пользователя к встрече (notes.md рядом с записью) — это пишет он сам, не движок
    notes = (m.folder / "notes.md").read_text().strip() if (m.folder / "notes.md").exists() else ""
    if notes:
        parts.append("## The user's own notes\n" + notes)
    return "\n\n".join(parts)


@server.tool(title="Read a transcript", annotations=READ)
def get_transcript(
    meeting: Annotated[str, Field(description="Meeting id from search or list_meetings")],
    start: Annotated[str | None, Field(description="Where in the recording to start: 12:30 or 1:02:03; "
                                                   "empty — from the beginning")] = None,
    end: Annotated[str | None, Field(description="Where in the recording to stop; empty — to the end")] = None,
) -> str:
    """The transcript turn by turn: "[time] Name: text". For exact wording and context: "What exactly did Priya say
    about the deadline?", "Quote the client's objection". Read a long meeting (an hour is about 60,000 characters)
    in pieces around the place search pointed to. Read-only."""
    m, rooms = find(meeting)
    since, until = seconds(start) if start else 0, seconds(end) if end else float("inf")
    # У монолога один голос — имена спикеров не нужны
    lines = [f"[{clock(t['start'])}] " + (t["text"] if m.monologue else f"{m.name(t['speaker'])}: {t['text']}")
             for t in m.turns() if t["end"] > since and t["start"] < until]
    return m.header(rooms) + "\n\n" + ("\n".join(lines) or "No turns in this part of the recording")


def main():
    """Точка входа пакета: `kedimeet-mcp [папка встреч]` (uvx kedimeet-mcp)."""
    server.run()


if __name__ == "__main__":
    main()
