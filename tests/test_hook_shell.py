import json
import subprocess
import sys

from mempalace import hook_shell


def test_normalize_transcript_path_preserves_windows_drive_and_segments():
    path = r"C:\Users\me\.claude\projects\-Users-me-Proj\session.jsonl"

    assert (
        hook_shell.normalize_transcript_path(path)
        == "C:/Users/me/.claude/projects/-Users-me-Proj/session.jsonl"
    )


def test_normalize_transcript_path_preserves_spaces_and_unicode():
    path = r"C:\Users\Me User\.claude\projects\emoji 🧠\session.jsonl"

    assert (
        hook_shell.normalize_transcript_path(path)
        == "C:/Users/Me User/.claude/projects/emoji 🧠/session.jsonl"
    )


def test_parse_stop_payload_keeps_session_strict_but_path_not_over_sanitized():
    session_id, stop_active, transcript_path = hook_shell.parse_stop_payload(
        {
            "session_id": "../bad session!!",
            "stop_hook_active": "yes",
            "transcript_path": r"C:\Users\Me User\.claude\projects\emoji 🧠\session.jsonl",
        }
    )

    assert session_id == "badsession"
    assert stop_active == "True"
    assert transcript_path == "C:/Users/Me User/.claude/projects/emoji 🧠/session.jsonl"


def test_parse_precompact_cli_outputs_sentinel_and_normalized_path():
    payload = {
        "session_id": "sess-1",
        "transcript_path": r"D:\Claude\projects\-Users-me-App\session.jsonl",
    }

    result = subprocess.run(
        [sys.executable, "-m", "mempalace.hook_shell", "parse-precompact"],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        check=True,
    )

    assert result.stdout.splitlines() == [
        "__MEMPAL_PARSE_OK__",
        "sess-1",
        "D:/Claude/projects/-Users-me-App/session.jsonl",
    ]


def test_count_human_messages_reads_utf8_transcripts_tolerantly(tmp_path):
    transcript = tmp_path / "session.jsonl"
    transcript.write_text(
        json.dumps(
            {"message": {"role": "user", "content": "emoji: 🧠 café Привет"}},
            ensure_ascii=False,
        )
        + "\n"
        + json.dumps({"message": {"role": "assistant", "content": "ignored"}})
        + "\n"
        + "{bad json\n",
        encoding="utf-8",
    )

    assert hook_shell.count_human_messages(str(transcript)) == 1

    result = subprocess.run(
        [sys.executable, "-m", "mempalace.hook_shell", "count-human-messages", str(transcript)],
        text=True,
        capture_output=True,
        check=True,
    )

    assert result.stdout.strip() == "1"
