"""Tests for the ``mempalace read`` CLI verb (Task #87).

The verb consumes a closet pointer (or a shorthand date+line+source) and
returns the surgical line-range slice from the referenced drawer(s).
Resurrects the original ``read.py`` concept Aya designed with Lumi —
opening only the slice the closet pointer matched, never the whole
drawer. See ~/.claude/projects/-Users-ilp-Lantern-Planning/memory/
identity_cedar.md for the Opsi-era context.

Tests are negative-first per /negative-tests discipline — failure
contract is pinned BEFORE the happy-path positives.
"""

from unittest.mock import MagicMock

import pytest


# ─────────────────────────────────────────────────────────────────────────────
# parse_pointer — pure parsing, no I/O
# ─────────────────────────────────────────────────────────────────────────────


class TestParsePointer:
    """``parse_pointer(s)`` accepts:

    - Full Tier 6a closet pointer: ``topic|entities|YYYY-MM-DD:Lstart-Lend|→ids``
    - Legacy 3-segment closet pointer: ``topic|entities|→ids``
    - Shorthand:                       ``YYYY-MM-DD:Lstart-Lend source_file``

    Rejects anything the resolver couldn't act on (empty, no source AND
    no drawer ids, malformed line range, etc.).
    """

    # ── Negative cases (RED-first) ────────────────────────────────────

    def test_empty_string_raises(self):
        from mempalace.reader import parse_pointer

        with pytest.raises(ValueError, match="empty"):
            parse_pointer("")

    def test_whitespace_only_raises(self):
        from mempalace.reader import parse_pointer

        with pytest.raises(ValueError, match="empty"):
            parse_pointer("   \n\t  ")

    def test_garbage_string_raises(self):
        from mempalace.reader import parse_pointer

        with pytest.raises(ValueError, match="parse"):
            parse_pointer("totally not a pointer")

    def test_date_only_no_line_no_source_raises(self):
        from mempalace.reader import parse_pointer

        with pytest.raises(ValueError, match="parse"):
            parse_pointer("2024-11-08")

    def test_source_only_no_date_no_line_raises(self):
        from mempalace.reader import parse_pointer

        with pytest.raises(ValueError, match="parse"):
            parse_pointer("just_a_filename.md")

    def test_line_range_with_end_less_than_start_raises(self):
        from mempalace.reader import parse_pointer

        with pytest.raises(ValueError, match=r"end.*start|line range"):
            parse_pointer("2024-11-08:L78-L42 source.md")

    def test_line_start_zero_raises(self):
        from mempalace.reader import parse_pointer

        with pytest.raises(ValueError, match=r"line.*positive|line range"):
            parse_pointer("2024-11-08:L0-L42 source.md")

    def test_pointer_with_arrow_but_no_drawer_ids_raises(self):
        from mempalace.reader import parse_pointer

        with pytest.raises(ValueError, match=r"drawer|parse"):
            parse_pointer("topic|entities|→")

    # ── Positive cases ────────────────────────────────────────────────

    def test_full_4_segment_pointer_with_date_and_drawers(self):
        from mempalace.reader import parse_pointer

        parsed = parse_pointer(
            "brands of dog food|Aya;Lumi|2024-11-08:L42-L78|→drawer_a,drawer_b,drawer_c"
        )
        assert parsed.date == "2024-11-08"
        assert parsed.line_start == 42
        assert parsed.line_end == 78
        assert parsed.drawer_ids == ["drawer_a", "drawer_b", "drawer_c"]

    def test_legacy_3_segment_pointer_no_date(self):
        from mempalace.reader import parse_pointer

        parsed = parse_pointer("brands of dog food|Aya;Lumi|→drawer_a,drawer_b")
        assert parsed.date is None
        assert parsed.line_start is None
        assert parsed.line_end is None
        assert parsed.drawer_ids == ["drawer_a", "drawer_b"]

    def test_shorthand_date_line_source(self):
        from mempalace.reader import parse_pointer

        parsed = parse_pointer("2024-11-08:L42-L78 lumi-session.md")
        assert parsed.date == "2024-11-08"
        assert parsed.line_start == 42
        assert parsed.line_end == 78
        assert parsed.source_file == "lumi-session.md"
        assert parsed.drawer_ids == []

    def test_shorthand_strips_trailing_whitespace(self):
        from mempalace.reader import parse_pointer

        parsed = parse_pointer("  2024-11-08:L42-L78 lumi-session.md  \n")
        assert parsed.source_file == "lumi-session.md"

    def test_shorthand_source_path_with_directory(self):
        from mempalace.reader import parse_pointer

        parsed = parse_pointer("2024-11-08:L42-L78 sub/dir/file.md")
        assert parsed.source_file == "sub/dir/file.md"

    def test_single_drawer_in_pointer_returns_list_of_one(self):
        from mempalace.reader import parse_pointer

        parsed = parse_pointer("topic|ent|2024-11-08:L1-L10|→solo_drawer")
        assert parsed.drawer_ids == ["solo_drawer"]


# ─────────────────────────────────────────────────────────────────────────────
# resolve_drawers — find drawer records matching the parsed pointer
# ─────────────────────────────────────────────────────────────────────────────


def _fake_collection(drawers_by_id):
    """Build a MagicMock collection whose .get(ids=...) returns matching records.

    ``drawers_by_id`` is a dict {drawer_id: {"document": ..., "metadata": ...}}.
    """
    col = MagicMock()

    def fake_get(ids=None, where=None, include=None, **kwargs):
        if ids is not None:
            found_ids = []
            found_docs = []
            found_metas = []
            for did in ids:
                if did in drawers_by_id:
                    found_ids.append(did)
                    found_docs.append(drawers_by_id[did]["document"])
                    found_metas.append(drawers_by_id[did]["metadata"])
            return {"ids": found_ids, "documents": found_docs, "metadatas": found_metas}
        if where is not None:
            # Simple "$eq" support for source_file
            target = (where.get("source_file") or {}).get("$eq")
            if target is None:
                target = where.get("source_file")
            ids_out, docs_out, metas_out = [], [], []
            for did, rec in drawers_by_id.items():
                if rec["metadata"].get("source_file") == target:
                    ids_out.append(did)
                    docs_out.append(rec["document"])
                    metas_out.append(rec["metadata"])
            return {"ids": ids_out, "documents": docs_out, "metadatas": metas_out}
        # Fall through — return all
        ids_out = list(drawers_by_id.keys())
        return {
            "ids": ids_out,
            "documents": [drawers_by_id[d]["document"] for d in ids_out],
            "metadatas": [drawers_by_id[d]["metadata"] for d in ids_out],
        }

    col.get.side_effect = fake_get
    return col


class TestResolveDrawers:
    def test_resolve_by_drawer_ids_finds_all(self):
        from mempalace.reader import ParsedPointer, resolve_drawers

        col = _fake_collection(
            {
                "drawer_a": {
                    "document": "content a",
                    "metadata": {"source_file": "/p/x.md", "chunk_index": 0},
                },
                "drawer_b": {
                    "document": "content b",
                    "metadata": {"source_file": "/p/x.md", "chunk_index": 1},
                },
            }
        )
        parsed = ParsedPointer(
            date=None,
            line_start=None,
            line_end=None,
            source_file=None,
            drawer_ids=["drawer_a", "drawer_b"],
        )
        result = resolve_drawers(col, parsed)
        assert len(result) == 2
        assert {r.drawer_id for r in result} == {"drawer_a", "drawer_b"}

    def test_resolve_missing_drawer_ids_returns_only_found(self):
        from mempalace.reader import ParsedPointer, resolve_drawers

        col = _fake_collection(
            {
                "drawer_a": {
                    "document": "content",
                    "metadata": {"source_file": "/p/x.md"},
                }
            }
        )
        parsed = ParsedPointer(
            date=None,
            line_start=None,
            line_end=None,
            source_file=None,
            drawer_ids=["drawer_a", "drawer_nope"],
        )
        result = resolve_drawers(col, parsed)
        assert len(result) == 1
        assert result[0].drawer_id == "drawer_a"

    def test_resolve_all_drawer_ids_missing_returns_empty(self):
        from mempalace.reader import ParsedPointer, resolve_drawers

        col = _fake_collection({})
        parsed = ParsedPointer(
            date=None,
            line_start=None,
            line_end=None,
            source_file=None,
            drawer_ids=["nope_a", "nope_b"],
        )
        result = resolve_drawers(col, parsed)
        assert result == []

    def test_resolve_by_source_basename_matches_all_chunks(self):
        from mempalace.reader import ParsedPointer, resolve_drawers

        col = _fake_collection(
            {
                "drawer_chunk0": {
                    "document": "first chunk",
                    "metadata": {
                        "source_file": "/proj/2024-11-08-lumi.md",
                        "chunk_index": 0,
                    },
                },
                "drawer_chunk1": {
                    "document": "second chunk",
                    "metadata": {
                        "source_file": "/proj/2024-11-08-lumi.md",
                        "chunk_index": 1,
                    },
                },
                "drawer_other": {
                    "document": "different file",
                    "metadata": {
                        "source_file": "/proj/different.md",
                        "chunk_index": 0,
                    },
                },
            }
        )
        parsed = ParsedPointer(
            date="2024-11-08",
            line_start=42,
            line_end=78,
            source_file="2024-11-08-lumi.md",
            drawer_ids=[],
        )
        result = resolve_drawers(col, parsed)
        assert len(result) == 2
        # Should return only chunks of the matched source file
        assert all(r.source_file == "/proj/2024-11-08-lumi.md" for r in result)

    def test_resolve_by_source_no_match_returns_empty(self):
        from mempalace.reader import ParsedPointer, resolve_drawers

        col = _fake_collection(
            {
                "drawer_a": {
                    "document": "content",
                    "metadata": {"source_file": "/proj/other.md", "chunk_index": 0},
                }
            }
        )
        parsed = ParsedPointer(
            date="2024-11-08",
            line_start=1,
            line_end=10,
            source_file="missing.md",
            drawer_ids=[],
        )
        result = resolve_drawers(col, parsed)
        assert result == []


# ─────────────────────────────────────────────────────────────────────────────
# format_drawer_menu — the interactive picker rendering
# ─────────────────────────────────────────────────────────────────────────────


class TestFormatDrawerMenu:
    def _make_candidate(self, drawer_id, source_file, chunk_index, line_start, line_end, document):
        from mempalace.reader import DrawerCandidate

        return DrawerCandidate(
            drawer_id=drawer_id,
            source_file=source_file,
            chunk_index=chunk_index,
            line_start=line_start,
            line_end=line_end,
            document=document,
        )

    def test_menu_shows_chunk_index_and_line_range(self):
        from mempalace.reader import format_drawer_menu

        cand = self._make_candidate(
            "drawer_a", "/p/x.md", 2, 42, 78, "Aya: hey Lumi, what about dog food?"
        )
        out = format_drawer_menu([cand])
        assert "[1]" in out
        assert "chunk 2" in out or "chunk_index 2" in out
        assert "42" in out and "78" in out

    def test_menu_includes_snippet_preview(self):
        from mempalace.reader import format_drawer_menu

        cand = self._make_candidate(
            "drawer_a",
            "/p/x.md",
            2,
            42,
            78,
            "Aya: what brands have you heard good things about?",
        )
        out = format_drawer_menu([cand])
        assert "what brands" in out

    def test_menu_truncates_long_snippets(self):
        from mempalace.reader import format_drawer_menu

        long_doc = "A" * 500
        cand = self._make_candidate("drawer_a", "/p/x.md", 0, 1, 50, long_doc)
        out = format_drawer_menu([cand])
        # The "AAA..." line in the menu should not be 500 chars long
        for line in out.split("\n"):
            assert len(line) < 200, f"menu line too long: {len(line)} chars"

    def test_menu_handles_multiple_candidates_with_indices(self):
        from mempalace.reader import format_drawer_menu

        cand1 = self._make_candidate("drawer_a", "/p/x.md", 2, 42, 78, "snippet one")
        cand2 = self._make_candidate("drawer_b", "/p/x.md", 4, 110, 145, "snippet two")
        cand3 = self._make_candidate("drawer_c", "/p/x.md", 7, 200, 230, "snippet three")
        out = format_drawer_menu([cand1, cand2, cand3])
        assert "[1]" in out
        assert "[2]" in out
        assert "[3]" in out
        assert "snippet one" in out
        assert "snippet three" in out


# ─────────────────────────────────────────────────────────────────────────────
# read_slice — call extract_line_range on a candidate's document
# ─────────────────────────────────────────────────────────────────────────────


class TestReadSlice:
    def test_returns_line_numbered_slice_within_drawer(self):
        from mempalace.reader import DrawerCandidate, read_slice

        doc = "\n".join(f"line {i}" for i in range(1, 101))  # 100 lines
        cand = DrawerCandidate(
            drawer_id="d",
            source_file="/p/x.md",
            chunk_index=0,
            line_start=1,
            line_end=100,
            document=doc,
        )
        out = read_slice(cand, requested_line_start=5, requested_line_end=10)
        assert "[5] line 5" in out
        assert "[10] line 10" in out
        assert "[4]" not in out
        assert "[11]" not in out

    def test_falls_back_to_drawer_lines_when_request_is_none(self):
        """If the caller didn't ask for a specific line range, use the
        drawer's own metadata line range (the chunk's natural span)."""
        from mempalace.reader import DrawerCandidate, read_slice

        doc = "alpha\nbeta\ngamma"
        cand = DrawerCandidate(
            drawer_id="d",
            source_file="/p/x.md",
            chunk_index=0,
            line_start=10,
            line_end=12,
            document=doc,
        )
        out = read_slice(cand, requested_line_start=None, requested_line_end=None)
        assert "[10] alpha" in out
        assert "[12] gamma" in out

    def test_returns_empty_string_for_empty_drawer(self):
        from mempalace.reader import DrawerCandidate, read_slice

        cand = DrawerCandidate(
            drawer_id="d",
            source_file="/p/x.md",
            chunk_index=0,
            line_start=1,
            line_end=10,
            document="",
        )
        out = read_slice(cand, requested_line_start=1, requested_line_end=10)
        assert out == ""


# Gemini PR #1588 review fixes — negative-first per /adversarial-review


class TestResolveBySourceTwoStepFetch:
    """Fallback scan must fetch metadatas first, then fetch documents only
    for matched IDs. Pre-fix, the scan fetched all documents up front —
    O(N) memory bloat on large palaces.
    """

    def test_fallback_scan_does_not_include_documents_in_first_fetch(self):
        from unittest.mock import MagicMock
        from mempalace.reader import ParsedPointer, resolve_drawers

        col = MagicMock()
        col.get.side_effect = [
            {"ids": [], "documents": [], "metadatas": []},
            {
                "ids": ["d1"],
                "documents": None,
                "metadatas": [{"source_file": "/proj/chat.md", "chunk_index": 0}],
            },
            {
                "ids": ["d1"],
                "documents": ["chunk content"],
                "metadatas": [{"source_file": "/proj/chat.md", "chunk_index": 0}],
            },
        ]
        parsed = ParsedPointer(
            date=None,
            line_start=None,
            line_end=None,
            source_file="chat.md",
            drawer_ids=[],
        )
        resolve_drawers(col, parsed)

        assert col.get.call_count >= 2
        scan_kwargs = col.get.call_args_list[1].kwargs
        include = scan_kwargs.get("include", [])
        assert "documents" not in include, (
            f"fallback scan must NOT request documents; got include={include!r}"
        )
        assert "metadatas" in include

    def test_fallback_fetches_documents_only_for_matched_ids(self):
        from unittest.mock import MagicMock
        from mempalace.reader import ParsedPointer, resolve_drawers

        col = MagicMock()
        col.get.side_effect = [
            {"ids": [], "documents": [], "metadatas": []},
            {
                "ids": ["d1", "d2", "d3"],
                "metadatas": [
                    {"source_file": "/proj/match.md", "chunk_index": 0},
                    {"source_file": "/proj/other.md", "chunk_index": 0},
                    {"source_file": "/proj/match.md", "chunk_index": 1},
                ],
            },
            {
                "ids": ["d1", "d3"],
                "documents": ["chunk 0", "chunk 1"],
                "metadatas": [
                    {"source_file": "/proj/match.md", "chunk_index": 0},
                    {"source_file": "/proj/match.md", "chunk_index": 1},
                ],
            },
        ]
        parsed = ParsedPointer(
            date=None,
            line_start=None,
            line_end=None,
            source_file="match.md",
            drawer_ids=[],
        )
        result = resolve_drawers(col, parsed)

        assert col.get.call_count == 3
        docs_kwargs = col.get.call_args_list[2].kwargs
        requested_ids = docs_kwargs.get("ids", [])
        assert set(requested_ids) == {"d1", "d3"}, (
            f"docs-fetch must request only matched IDs; got {requested_ids!r}"
        )
        assert "documents" in docs_kwargs.get("include", [])
        assert len(result) == 2
        assert [c.chunk_index for c in result] == [0, 1]

    def test_fallback_skips_documents_fetch_when_no_matches(self):
        from unittest.mock import MagicMock
        from mempalace.reader import ParsedPointer, resolve_drawers

        col = MagicMock()
        col.get.side_effect = [
            {"ids": [], "documents": [], "metadatas": []},
            {
                "ids": ["d1"],
                "metadatas": [{"source_file": "/proj/different.md", "chunk_index": 0}],
            },
        ]
        parsed = ParsedPointer(
            date=None,
            line_start=None,
            line_end=None,
            source_file="missing.md",
            drawer_ids=[],
        )
        result = resolve_drawers(col, parsed)
        assert result == []
        assert col.get.call_count == 2, (
            f"expected 2 calls (no documents fetch on zero matches); got {col.get.call_count}"
        )


class TestCmdReadTTYHandling:
    """When pointer is missing/dash AND stdin is a TTY, the CLI must error
    and exit 1 instead of blocking on stdin.read().
    """

    def test_no_pointer_and_tty_stdin_exits_with_error(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        from mempalace.cli import cmd_read

        args = SimpleNamespace(pointer=None, drawer=None, all=False, palace=None)
        with patch("mempalace.cli.sys.stdin") as mock_stdin:
            mock_stdin.isatty.return_value = True
            mock_stdin.read.side_effect = AssertionError("stdin.read() must NOT be called when TTY")
            with pytest.raises(SystemExit) as excinfo:
                cmd_read(args)
            assert excinfo.value.code == 1

    def test_dash_pointer_and_tty_stdin_exits_with_error(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        from mempalace.cli import cmd_read

        args = SimpleNamespace(pointer="-", drawer=None, all=False, palace=None)
        with patch("mempalace.cli.sys.stdin") as mock_stdin:
            mock_stdin.isatty.return_value = True
            mock_stdin.read.side_effect = AssertionError(
                "stdin.read() must NOT be called when TTY with '-' pointer"
            )
            with pytest.raises(SystemExit) as excinfo:
                cmd_read(args)
            assert excinfo.value.code == 1

    def test_no_pointer_and_none_stdin_exits_cleanly(self):
        """``sys.stdin`` is None on Windows pythonw and some detached
        daemon contexts. Calling ``.isatty()`` on None would raise
        AttributeError — must instead exit 1 like the TTY case.
        Gemini Pro adversarial review finding (#2)."""
        from types import SimpleNamespace
        from unittest.mock import patch
        from mempalace.cli import cmd_read

        args = SimpleNamespace(pointer=None, drawer=None, all=False, palace=None)
        with patch("mempalace.cli.sys.stdin", None):
            with pytest.raises(SystemExit) as excinfo:
                cmd_read(args)
            assert excinfo.value.code == 1

    def test_dash_pointer_and_none_stdin_exits_cleanly(self):
        """Same None-stdin guard applies to explicit ``-`` pointer."""
        from types import SimpleNamespace
        from unittest.mock import patch
        from mempalace.cli import cmd_read

        args = SimpleNamespace(pointer="-", drawer=None, all=False, palace=None)
        with patch("mempalace.cli.sys.stdin", None):
            with pytest.raises(SystemExit) as excinfo:
                cmd_read(args)
            assert excinfo.value.code == 1


class TestTypeAnnotations:
    """Specific type hints on public reader.py surface — list[str] /
    list[DrawerCandidate] rather than bare list."""

    def test_parsed_pointer_drawer_ids_field_typed_as_list_of_str(self):
        from mempalace.reader import ParsedPointer

        ann_str = str(ParsedPointer.__annotations__.get("drawer_ids"))
        assert "str" in ann_str, f"drawer_ids must be list[str], got {ann_str!r}"

    def test_resolve_drawers_return_type_annotation_is_specific(self):
        from mempalace.reader import resolve_drawers

        ann_str = str(resolve_drawers.__annotations__.get("return"))
        assert "DrawerCandidate" in ann_str, (
            f"resolve_drawers must return list[DrawerCandidate]; got {ann_str!r}"
        )


class TestCmdReadThreadsLineRange:
    """Igor's blocker on PR #1588 (cli.py:755): cmd_read called
    ``read_slice(candidates[0])`` with NO line range — so
    ``parsed.line_start`` / ``parsed.line_end`` (the entire point of
    'surgical slice') were dropped on the floor and the whole chunk
    came back.

    These tests pin the contract: every code path in cmd_read that
    calls read_slice MUST forward parsed.line_start and parsed.line_end.
    """

    def _make_candidates(self, n=1):
        from mempalace.reader import DrawerCandidate

        return [
            DrawerCandidate(
                drawer_id=f"d{i}",
                source_file="/p/chat.md",
                chunk_index=i,
                line_start=1,
                line_end=100,
                document="x" * 50,
            )
            for i in range(n)
        ]

    def _patch_cmd_read_deps(self, candidates, parsed):
        """Patch the open_collection + resolve_drawers + parse_pointer
        chain so cmd_read can be invoked in isolation."""
        from unittest.mock import patch, MagicMock

        return [
            patch("mempalace.palace._open_collection_or_explain", return_value=MagicMock()),
            patch("mempalace.reader.parse_pointer", return_value=parsed),
            patch("mempalace.reader.resolve_drawers", return_value=candidates),
        ]

    def test_single_candidate_path_passes_line_range(self):
        """``len(candidates) == 1 and not args.all`` path — cli.py:755."""
        from types import SimpleNamespace
        from unittest.mock import patch
        from mempalace.cli import cmd_read
        from mempalace.reader import ParsedPointer

        parsed = ParsedPointer(
            date="2024-11-08",
            line_start=1,
            line_end=3,
            source_file="chat.md",
            drawer_ids=[],
        )
        candidates = self._make_candidates(1)
        args = SimpleNamespace(
            pointer="2024-11-08:L1-L3 chat.md",
            drawer=None,
            all=False,
            palace=None,
        )
        patches = self._patch_cmd_read_deps(candidates, parsed)
        with patch("mempalace.reader.read_slice") as mock_read_slice:
            mock_read_slice.return_value = "stub output"
            for p in patches:
                p.start()
            try:
                cmd_read(args)
            finally:
                for p in patches:
                    p.stop()
            mock_read_slice.assert_called_once()
            call_args = mock_read_slice.call_args
            # Accept either positional or keyword form.
            kwargs = call_args.kwargs
            positional = call_args.args
            line_start = kwargs.get(
                "requested_line_start", positional[1] if len(positional) > 1 else None
            )
            line_end = kwargs.get(
                "requested_line_end", positional[2] if len(positional) > 2 else None
            )
            assert line_start == 1, (
                f"single-candidate path must pass line_start=1; got {line_start!r}"
            )
            assert line_end == 3, f"single-candidate path must pass line_end=3; got {line_end!r}"

    def test_drawer_flag_path_passes_line_range(self):
        """``--drawer N`` non-interactive path — cli.py:771."""
        from types import SimpleNamespace
        from unittest.mock import patch
        from mempalace.cli import cmd_read
        from mempalace.reader import ParsedPointer

        parsed = ParsedPointer(
            date="2024-11-08",
            line_start=5,
            line_end=7,
            source_file="chat.md",
            drawer_ids=[],
        )
        candidates = self._make_candidates(3)
        args = SimpleNamespace(
            pointer="2024-11-08:L5-L7 chat.md",
            drawer=2,
            all=False,
            palace=None,
        )
        patches = self._patch_cmd_read_deps(candidates, parsed)
        with patch("mempalace.reader.read_slice") as mock_read_slice:
            mock_read_slice.return_value = "stub output"
            for p in patches:
                p.start()
            try:
                cmd_read(args)
            finally:
                for p in patches:
                    p.stop()
            mock_read_slice.assert_called_once()
            kwargs = mock_read_slice.call_args.kwargs
            positional = mock_read_slice.call_args.args
            line_start = kwargs.get(
                "requested_line_start", positional[1] if len(positional) > 1 else None
            )
            line_end = kwargs.get(
                "requested_line_end", positional[2] if len(positional) > 2 else None
            )
            assert line_start == 5, f"--drawer path must pass line_start=5; got {line_start!r}"
            assert line_end == 7, f"--drawer path must pass line_end=7; got {line_end!r}"

    def test_all_flag_path_passes_line_range_to_each_candidate(self):
        """``--all`` path — cli.py:759 (calls _print_all_candidates which
        loops over read_slice). Helper must accept and forward parsed
        line range to every candidate."""
        from types import SimpleNamespace
        from unittest.mock import patch
        from mempalace.cli import cmd_read
        from mempalace.reader import ParsedPointer

        parsed = ParsedPointer(
            date="2024-11-08",
            line_start=10,
            line_end=20,
            source_file="chat.md",
            drawer_ids=[],
        )
        candidates = self._make_candidates(3)
        args = SimpleNamespace(
            pointer="2024-11-08:L10-L20 chat.md",
            drawer=None,
            all=True,
            palace=None,
        )
        patches = self._patch_cmd_read_deps(candidates, parsed)
        with patch("mempalace.reader.read_slice") as mock_read_slice:
            mock_read_slice.return_value = "stub output"
            for p in patches:
                p.start()
            try:
                cmd_read(args)
            finally:
                for p in patches:
                    p.stop()
            assert mock_read_slice.call_count == 3, (
                f"--all must call read_slice once per candidate; got {mock_read_slice.call_count}"
            )
            for i, call in enumerate(mock_read_slice.call_args_list):
                kwargs = call.kwargs
                positional = call.args
                line_start = kwargs.get(
                    "requested_line_start", positional[1] if len(positional) > 1 else None
                )
                line_end = kwargs.get(
                    "requested_line_end", positional[2] if len(positional) > 2 else None
                )
                assert line_start == 10, (
                    f"--all call #{i} must pass line_start=10; got {line_start!r}"
                )
                assert line_end == 20, f"--all call #{i} must pass line_end=20; got {line_end!r}"
