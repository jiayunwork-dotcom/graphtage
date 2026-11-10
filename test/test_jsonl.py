import json
import os
import tempfile
from io import StringIO
from unittest import TestCase

import graphtage
import graphtage.jsonl
from graphtage.printer import Printer
from graphtage.utils import Tempfile

FILETYPE = graphtage.FILETYPES_BY_TYPENAME['jsonl']


def build(content: bytes) -> graphtage.TreeNode:
    with Tempfile(content) as path:
        return FILETYPE.build_tree(path)


def render(from_content: bytes, to_content: bytes | None = None) -> str:
    """Renders the JSON Lines diff of two documents without ANSI color."""
    if to_content is None:
        to_content = from_content
    stream = StringIO()
    printer = Printer(out_stream=stream, ansi_color=False, quiet=True)
    diff = build(from_content).diff(build(to_content))
    FILETYPE.get_default_formatter().print(printer, diff)
    printer.flush(final=True)
    return stream.getvalue()


class TestJSONLParsing(TestCase):
    def test_each_non_empty_line_is_a_record(self):
        tree = build(b'{"a": 1}\n2\n"three"\n')
        self.assertIsInstance(tree, graphtage.jsonl.JSONLNode)
        self.assertEqual([{"a": 1}, 2, "three"], tree.to_obj())

    def test_crlf_line_endings_are_accepted(self):
        tree = build(b'{"a": 1}\r\n{"b": 2}\r\n')
        self.assertEqual([{"a": 1}, {"b": 2}], tree.to_obj())

    def test_blank_lines_are_ignored(self):
        # Empty lines, whitespace-only lines, leading and trailing blanks, and CRLF blanks are all tolerated.
        tree = build(b'\n{"a": 1}\r\n\r\n   \n{"b": 2}\n\n')
        self.assertEqual([{"a": 1}, {"b": 2}], tree.to_obj())

    def test_blank_lines_are_not_records(self):
        """Ignoring a blank line must not insert a placeholder record into the tree."""
        tree = build(b'{"a": 1}\n\n{"b": 2}\n')
        self.assertEqual(2, len(tree))

    def test_empty_file_builds_an_empty_record_list(self):
        self.assertEqual([], build(b'').to_obj())
        self.assertEqual([], build(b'\n  \r\n').to_obj())

    def test_parse_error_names_the_file_and_line_number(self):
        directory = tempfile.mkdtemp()
        path = os.path.join(directory, 'broken.jsonl')
        with open(path, 'w') as f:
            f.write('{"a": 1}\n{"b": 2}\n{oops\n')
        with self.assertRaises(graphtage.jsonl.JSONLParseError) as failure:
            FILETYPE.build_tree(path)
        error = failure.exception
        self.assertEqual(path, error.path)
        self.assertEqual(3, error.line_number)
        self.assertIn('broken.jsonl', str(error))
        self.assertIn('line 3', str(error))

    def test_parse_error_reports_the_physical_line_after_blank_lines(self):
        """Blank lines are skipped, but the reported line number is still the line's position in the file."""
        directory = tempfile.mkdtemp()
        path = os.path.join(directory, 'broken.jsonl')
        with open(path, 'w') as f:
            f.write('{"a": 1}\n\n\n{oops\n')
        with self.assertRaises(graphtage.jsonl.JSONLParseError) as failure:
            FILETYPE.build_tree(path)
        self.assertEqual(4, failure.exception.line_number)

    def test_build_tree_handling_errors_returns_a_message(self):
        directory = tempfile.mkdtemp()
        path = os.path.join(directory, 'broken.ndjson')
        with open(path, 'w') as f:
            f.write('"valid"\n{\n')
        result = FILETYPE.build_tree_handling_errors(path)
        self.assertIsInstance(result, str)
        self.assertIn('broken.ndjson', result)
        self.assertIn('line 2', result)

    def test_registered_mime_types(self):
        self.assertEqual('jsonl', FILETYPE.name)
        self.assertEqual('application/jsonl', FILETYPE.default_mimetype)
        self.assertIn('application/x-ndjson', FILETYPE.mimetypes)


class TestJSONLRenderedDiffs(TestCase):
    """Covers the diff path, which the ``@filetype_test`` round trip cannot reach because it only prints unedited trees."""

    def test_field_edit_stays_on_one_record_line(self):
        self.assertEqual(
            '{"id": 1, "v": "foo++s++"}\n',
            render(b'{"id": 1, "v": "foo"}\n', b'{"id": 1, "v": "foos"}\n')
        )

    def test_inserted_record_is_marked(self):
        self.assertEqual(
            '{"a": 1}\n++{"b": 2}++\n',
            render(b'{"a": 1}\n', b'{"a": 1}\n{"b": 2}\n')
        )

    def test_removed_record_is_marked(self):
        self.assertEqual(
            '{"a": 1}\n~~{"b": 2}~~\n',
            render(b'{"a": 1}\n{"b": 2}\n', b'{"a": 1}\n')
        )

    def test_leaf_records_render_without_brackets(self):
        self.assertEqual('1\n2 -> 3\n', render(b'1\n2\n', b'1\n3\n'))

    def test_nested_list_keeps_its_brackets_on_one_line(self):
        # Only the record list loses its brackets; a list nested inside a record is ordinary JSON.
        self.assertEqual(
            '{"a": [1, 2, ++3++]}\n',
            render(b'{"a": [1, 2]}\n', b'{"a": [1, 2, 3]}\n')
        )

    def test_nested_dict_stays_compact(self):
        rendered = render(b'{"a": {"b": 1}}\n', b'{"a": {"b": 2}}\n')
        self.assertEqual(1, rendered.count('\n'))
        self.assertEqual('{"a": {"b": 1 -> 2}}\n', rendered)

    def test_output_has_no_record_list_brackets_or_commas(self):
        rendered = render(b'{"a": 1}\n{"b": 2}\n', b'{"a": 1}\n{"b": 2}\n{"c": 3}\n')
        # Each record occupies exactly one line and no record-level comma or bracket is emitted.
        self.assertEqual(['{"a": 1}', '{"b": 2}', '++{"c": 3}++', ''], rendered.split('\n'))

    def test_identical_inputs_have_no_edit_markers(self):
        rendered = render(b'{"a": 1}\n{"b": 2}\n')
        self.assertNotIn('~~', rendered)
        self.assertNotIn('++', rendered)
        self.assertEqual(0, build(b'{"a": 1}\n').diff(build(b'{"a": 1}\n')).edited_cost())

    def test_unedited_output_is_valid_json_lines(self):
        rendered = render(b'{"a": 1}\n{"b": [1, 2]}\n')
        records = [json.loads(line) for line in rendered.splitlines() if line.strip()]
        self.assertEqual([{"a": 1}, {"b": [1, 2]}], records)
        self.assertEqual(2, len(rendered.splitlines()))
