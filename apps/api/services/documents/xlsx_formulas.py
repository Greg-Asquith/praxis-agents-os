# apps/api/services/documents/xlsx_formulas.py

"""Formula reference checks and sheet renames for workbook edits.

Runs only inside the document worker. openpyxl doesn't evaluate or rewrite
formulas, so edits tokenise them to find sheet, name, and table references.
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

_CELL = r"\$?[A-Za-z]{1,3}\$?[0-9]{1,7}"
_REFERENCE = re.compile(
    rf"^(?:{_CELL}(?::{_CELL})?|\$?[A-Za-z]{{1,3}}:\$?[A-Za-z]{{1,3}}|\$?[0-9]{{1,7}}:\$?[0-9]{{1,7}})$"
)
_PLAIN_SHEET = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]*$")
# LET and LAMBDA declare local names that aren't workbook names.
_LOCAL_NAME_FUNCTIONS = ("LET(", "LAMBDA(", "_XLFN.LET(", "_XLFN.LAMBDA(")


@dataclass(frozen=True)
class WorkbookNames:
    """Sheet, defined, and table names a formula can refer to, compared without case.

    `names` are workbook-level; `local_names` are keyed by the sheet that owns them.
    """

    sheets: frozenset[str]
    names: frozenset[str]
    local_names: Mapping[str, frozenset[str]]
    tables: frozenset[str]

    def has_name(self, defined: str, sheet: str | None) -> bool:
        key = defined.casefold()
        return key in self.names or (
            sheet is not None and key in self.local_names.get(sheet.casefold(), frozenset())
        )


def formula_problems(formula: str, known: WorkbookNames, *, sheet: str | None) -> list[str]:
    """Returns what's wrong with a formula's references, or an empty list.

    `sheet` is the sheet the formula lives on, which decides the local names it
    can use without a sheet prefix; None for a workbook-level name.
    """
    tokens = _tokens(formula)
    if tokens is None:
        return ["isn't a formula Excel can read"]
    local_names = any(
        token.type == "FUNC" and token.value.upper().startswith(_LOCAL_NAME_FUNCTIONS)
        for token in tokens
    )
    problems = []
    for token in tokens:
        if token.type != "OPERAND" or token.subtype not in ("RANGE", "ERROR"):
            continue
        if "#REF!" in token.value.upper():
            problems.append("refers to a deleted cell or sheet (#REF!)")
        elif token.subtype == "RANGE":
            problem = _reference_problem(token.value, known, sheet, local_names=local_names)
            if problem is not None:
                problems.append(problem)
    return problems


def referenced_sheets(formula: str) -> set[str]:
    """Returns the sheet names a formula refers to, compared without case."""
    sheets: set[str] = set()
    for token in _tokens(formula) or []:
        if token.type == "OPERAND" and token.subtype == "RANGE" and "!" in token.value:
            sheets.update(
                sheet.casefold() for sheet in _sheet_names(token.value.rpartition("!")[0])
            )
    return sheets


def rename_sheet(formula: str, old: str, new: str) -> str:
    """Returns the formula with references to sheet `old` pointing at `new`."""
    tokens = _tokens(formula)
    if tokens is None or not formula.startswith("="):
        return formula
    changed = False
    for token in tokens:
        if token.type != "OPERAND" or token.subtype != "RANGE" or "!" not in token.value:
            continue
        prefix, _, reference = token.value.rpartition("!")
        sheets = _sheet_names(prefix)
        if not sheets or not any(sheet.casefold() == old.casefold() for sheet in sheets):
            continue
        renamed = [new if sheet.casefold() == old.casefold() else sheet for sheet in sheets]
        token.value = f"{_quote(':'.join(renamed))}!{reference}"
        changed = True
    return "=" + "".join(token.value for token in tokens) if changed else formula


def _tokens(formula: str) -> list[Any] | None:
    from openpyxl.formula.tokenizer import Tokenizer, TokenizerError

    try:
        return Tokenizer(formula).items
    except (TokenizerError, IndexError, ValueError):
        return None


def _reference_problem(
    value: str, known: WorkbookNames, sheet: str | None, *, local_names: bool
) -> str | None:
    prefix, _, reference = value.rpartition("!")
    if prefix:
        if prefix.lstrip("'").startswith("["):
            return None
        sheets = _sheet_names(prefix)
        for named in sheets:
            if named.casefold() not in known.sheets:
                return f"refers to sheet {named[:100]!r}, which doesn't exist"
        # A sheet prefix picks the sheet whose local names apply.
        sheet = sheets[0] if len(sheets) == 1 else None
    if _REFERENCE.match(reference):
        return None
    if "[" in reference:
        table = reference.split("[", 1)[0]
        if table and table.casefold() not in known.tables:
            return f"refers to table {table[:100]!r}, which doesn't exist"
        return None
    if local_names or known.has_name(reference, sheet):
        return None
    return f"uses the name {reference[:100]!r}, which isn't defined"


def _sheet_names(prefix: str) -> list[str]:
    """Splits a sheet prefix, including a quoted or 3D one such as 'Q1:Q4', into sheet names."""
    if prefix.startswith("'") and prefix.endswith("'") and len(prefix) > 1:
        prefix = prefix[1:-1].replace("''", "'")
    if not prefix or prefix.startswith("["):
        return []
    return prefix.split(":")


def _quote(sheet: str) -> str:
    if _PLAIN_SHEET.match(sheet) and not _REFERENCE.match(sheet):
        return sheet
    return "'" + sheet.replace("'", "''") + "'"
