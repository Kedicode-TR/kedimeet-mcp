"""uv run test_server.py — сервер на маленькой библиотеке из двух встреч."""

import asyncio
import json
import tempfile
from pathlib import Path

import server


def meeting(root: Path, name: str, meta: dict, segments: list, summary: dict | None = None, done: bool = True) -> None:
    folder = root / name
    folder.mkdir()
    (folder / "meta.json").write_text(json.dumps(meta))
    (folder / "segments.json").write_text(json.dumps(segments))
    if summary:
        (folder / "summary.json").write_text(json.dumps(summary))
    if done:
        (folder / "meeting.md").write_text("")


def test() -> None:
    root = Path(tempfile.mkdtemp())
    server.LIBRARY = root
    (root / "rooms.json").write_text(json.dumps({"meet.google.com/abc-defg-hij": "Kick-Off по Тарифам"}))
    (root / "Записи").mkdir()  # не встреча: нет meta.json
    meeting(root, "Созвон 03.11.2026 10-59-37",
            {"source": "/x/Созвон 03.11.2026 10-59-37.m4a", "addedAt": "2026-11-03T09:01:21Z",
             "link": "https://meet.google.com/abc-defg-hij?authuser=0", "names": {"SPEAKER_00": "Майя"},
             "doneTasks": ["Дописать чек-листы"]},
            [{"start": 0, "end": 5, "text": " Начнём с тарифах.", "speaker": "SPEAKER_00"},
             {"start": 5, "end": 9, "text": "И с миграций.", "speaker": "SPEAKER_00"},
             {"start": 9, "end": 70, "text": "Я посмотрю.", "speaker": "SPEAKER_01"},
             {"start": 70, "end": 75, "text": "", "speaker": "SPEAKER_00"}],
            {"title": "Тарифы", "speakers": [{"label": "SPEAKER_01", "name": "Даниил", "evidence": "…"}],
             "short": ["SPEAKER_00 рассказала про тарифы"], "decisions": [], "open_questions": [],
             "tasks": [{"who": "SPEAKER_00", "what": "Дописать чек-листы", "due": None},
                       {"who": "SPEAKER_01", "what": "Посмотреть миграции", "due": "пятница"}]})
    meeting(root, "lecture",
            {"source": "/x/lecture.mp4", "addedAt": "2026-10-01T12:00:00Z"},
            [{"start": 0, "end": 3, "text": "Тариф старый.", "speaker": None}], done=False)

    listed = server.list_meetings()
    assert listed.index("Kick-Off по Тарифам") < listed.index("lecture"), listed  # имя по ссылке; новые сверху
    assert "participants: SPEAKER_01, Майя" in listed and "Майя рассказала" in listed, listed
    assert "no summary yet" in listed.split("[id: lecture]")[1], listed

    found = server.search("тарифы")
    assert "Matches: 3" in found, found  # резюме и реплика новой встречи, фраза старой
    assert "0:00, Майя: Майя: Начнём с тарифах. И с миграций." in found, found
    assert found.index("2026-11-03") < found.index("lecture"), found
    assert "lecture" not in server.search("тарифы", since="2026-11-01"), "период не отсёк старую встречу"
    assert server.search("Даниил миграции").startswith("Matches: 2"), server.search("Даниил миграции")
    assert "Nothing" in server.search("бюджет")

    one = server.get_meeting("Созвон 03.11.2026 10-59-37")
    assert "SPEAKER_01 (probably Даниил) — 87%" in one and "Майя — 13%" in one, one
    assert "- [x] Майя: Дописать чек-листы" in one and "- [ ] SPEAKER_01: Посмотреть миграции (due пятница)" in one, one
    assert "Duration: 1:10" in one, one  # пустая реплика в конце — не в счёт
    assert "own notes" not in one, one  # своих заметок нет — и раздела нет
    (root / "Созвон 03.11.2026 10-59-37" / "notes.md").write_text("[0:09] Даниил берёт миграции\n")
    assert server.get_meeting("Созвон 03.11.2026 10-59-37").endswith("## The user's own notes\n[0:09] Даниил берёт миграции")
    assert "No summary" in server.get_meeting("lecture")

    part = server.get_transcript("Созвон 03.11.2026 10-59-37", start="0:06", end="1:00")
    assert "[0:00] Майя" in part and "[0:09] SPEAKER_01: Я посмотрю." in part, part  # реплика, что задевает отрезок
    assert server.get_transcript("lecture").endswith("[0:00] ?: Тариф старый."), server.get_transcript("lecture")

    try:
        server.get_meeting("нет такой")
    except server.ToolError:
        pass
    else:
        raise AssertionError("неизвестная встреча должна быть ошибкой")

    assert server.stems("Тарифы тарифах iOS") == ["ios", "тари", "тариф"]
    assert server.seconds("1:02:03") == 3723 and server.clock(3723) == "1:02:03"
    # Имя записи зависит от языка приложения: русское и остальные (дата по ISO) — одна и та же дата
    ru, en = server.recorded_at("Созвон 03.11.2026 10-59-37"), server.recorded_at("Call 2026-11-03 10-59-37")
    assert ru is not None and ru == en and f"{en:%Y-%m-%d %H:%M}" == "2026-11-03 10:59", (ru, en)
    assert server.recorded_at("2026-11-03 notes") is not None and server.recorded_at("lecture") is None

    # Все четыре инструмента — только чтение, с названием и примерами живых вопросов: клиент показывает их отдельно
    tools = asyncio.run(server.server.list_tools())
    assert len(tools) == 4, [t.name for t in tools]
    for tool in tools:
        hints = tool.annotations
        assert hints.read_only_hint and hints.destructive_hint is False and hints.open_world_hint is False, tool.name
        assert tool.title and '?"' in tool.description and "Read-only." in tool.description, tool.name
    # Версия одна: пакет берёт её из server.py, реестр MCP — из server.json
    meta = json.loads((Path(__file__).parent / "server.json").read_text())
    assert meta["version"] == server.__version__ and {p["version"] for p in meta["packages"]} == {server.__version__}, meta
    assert len(meta["description"]) <= 100, "реестр MCP режет описание до 100 знаков"
    print("ok")


if __name__ == "__main__":
    test()
