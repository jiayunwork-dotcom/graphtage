"""A :class:`graphtage.Filetype` for parsing, diffing, and rendering `JSON Lines`_ files.

Each non-empty line of a JSON Lines file (also known as newline-delimited JSON, or NDJSON) is an independent JSON
value. The file is therefore parsed into an ordered list of records, one record per line, and rendered back with one
record per line: no enclosing square brackets and no commas between records. Blank lines are tolerated and ignored;
they are not treated as JSON values.

.. _JSON Lines:
    https://jsonlines.org/

"""
import json
import os

from .graphtage import BuildOptions, Filetype, ListNode
from .json import JSONFormatter
from .json import build_tree as build_json_tree
from .printer import Printer
from .sequences import SequenceFormatter
from .tree import TreeNode


class JSONLParseError(ValueError):
    """Raised when a non-empty line of a JSON Lines file is not valid JSON.

    Attributes:
        path: The path of the file that could not be parsed.
        line_number: The one-based line number of the invalid line within :attr:`path`.
        decode_error: The original error raised by :func:`json.loads`.

    """

    def __init__(self, path: str, line_number: int, decode_error: json.JSONDecodeError):
        self.path = path
        self.line_number = line_number
        self.decode_error = decode_error
        super().__init__(
            f'Error parsing {os.path.basename(path)}: {decode_error.msg}: line {line_number}, '
            f'column {decode_error.colno} (char {decode_error.pos})'
        )


class JSONLNode(ListNode[TreeNode]):
    """A node representing the records of a JSON Lines file."""


def build_tree(path: str, options: BuildOptions | None = None) -> JSONLNode:
    """Builds a :class:`JSONLNode` from a JSON Lines file.

    Each non-empty line is parsed with :func:`json.loads` and converted to a tree node by
    :func:`graphtage.json.build_tree`. Universal newline mode is used, so CRLF and lone CR line endings are accepted.
    Lines that are empty or contain only whitespace are skipped.

    Args:
        path: Path to the JSON Lines file to parse.
        options: An optional set of options for building the tree.

    Returns:
        JSONLNode: The resulting tree, with one child node per non-empty line.

    Raises:
        JSONLParseError: If a non-empty line is not valid JSON. The error names the file and the line number.

    """
    if options is None:
        options = BuildOptions()
    records = []
    with open(path, encoding='utf-8') as f:
        for line_number, line in enumerate(f, start=1):
            if not line.strip():
                # Blank lines are tolerated and ignored rather than parsed as JSON values.
                continue
            try:
                python_obj = json.loads(line)
            except json.JSONDecodeError as e:
                raise JSONLParseError(path, line_number, e) from e
            records.append(build_json_tree(python_obj, options))
    return JSONLNode(
        records,
        allow_list_edits=options.allow_list_edits,
        allow_list_edits_when_same_length=options.allow_list_edits_when_same_length
    )


class JSONLRecordFormatter(SequenceFormatter):
    """A sub-formatter for the record list of a JSON Lines file.

    The records are printed one per line, with no start or end symbol and no delimiter. Every value nested inside a
    record is ordinary JSON, so any sequence that is not the root :class:`JSONLNode` is handed back to the parent
    formatter, which resolves it through the JSON sub-formatters.

    """
    is_partial = True

    def __init__(self):
        """Initializes the formatter.

        Equivalent to::

            super().__init__('', '', '')

        """
        super().__init__('', '', '')

    def print_JSONLNode(self, *args, **kwargs):
        """Prints a :class:`JSONLNode`, forcing each of its records onto a single line.

        The JSON sub-formatters only keep a list or dictionary on one line when the printer's ``join_lists`` and
        ``join_dict_items`` options are set. A JSON Lines record must occupy a single line no matter how the user
        configured those options, so they are enabled for the duration of the print and restored afterward.

        """
        printer = args[0]
        joined_lists = getattr(printer, 'join_lists', False)
        joined_dict_items = getattr(printer, 'join_dict_items', False)
        printer.join_lists = True
        printer.join_dict_items = True
        try:
            super().print_SequenceNode(*args, **kwargs)
        finally:
            printer.join_lists = joined_lists
            printer.join_dict_items = joined_dict_items

    def print_SequenceNode(self, *args, **kwargs):
        """Prints a non-JSONL sequence as the JSON value it is inside a record.

        This delegates to the parent formatter::

            self.parent.print(*args, **kwargs)

        which resolves plain lists and dictionaries through the JSON sub-formatters, preserving their brackets and
        braces.

        """
        self.parent.print(*args, **kwargs)

    def item_newline(self, printer: Printer, is_first: bool = False, is_last: bool = False):
        """Prints a newline between records, but not before the first one."""
        if not is_first:
            printer.newline()

    def items_indent(self, printer: Printer) -> Printer:
        """Returns :obj:`printer` because records are not indented relative to one another."""
        return printer


class JSONLFormatter(JSONFormatter):
    """The default formatter for JSON Lines files.

    It behaves exactly like the :class:`~graphtage.json.JSONFormatter`, except that a root :class:`JSONLNode` is
    rendered as one record per line without an enclosing array.

    """
    sub_format_types = (JSONLRecordFormatter, *JSONFormatter.sub_format_types)


class JSONL(Filetype):
    """The JSON Lines file type."""

    def __init__(self):
        """Initializes the JSON Lines file type.

        By default, JSON Lines associates itself with the "jsonl", "application/jsonl", and
        "application/x-ndjson" MIME types.

        """
        super().__init__(
            'jsonl',
            'application/jsonl',
            'application/x-ndjson'
        )

    def build_tree(self, path: str, options: BuildOptions | None = None) -> TreeNode:
        """Equivalent to :func:`build_tree`"""
        return build_tree(path, options=options)

    def build_tree_handling_errors(self, path: str, options: BuildOptions | None = None) -> str | TreeNode:
        try:
            return self.build_tree(path=path, options=options)
        except JSONLParseError as e:
            return str(e)

    def get_default_formatter(self) -> JSONLFormatter:
        return JSONLFormatter.DEFAULT_INSTANCE
