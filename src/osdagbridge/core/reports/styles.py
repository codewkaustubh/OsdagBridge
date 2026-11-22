"""Shared report styling and longtable layout helpers."""

import re
from typing import Iterable, Sequence


osdagGreen = "#91B014"
OSDAG_GREEN = osdagGreen.lstrip("#")
STATUS_PASS = "#2E7D32"
STATUS_WARNING = "#E69F00"
STATUS_FAIL = "#C62828"
STATUS_NEUTRAL = "#666666"
THRESHOLD_REFERENCE = "#D32F2F"
CHART_PRIMARY = osdagGreen
CHART_SECONDARY = "#6F8F2F"
CHART_NEUTRAL = "#9AA7AD"
CHART_TERTIARY = "#83A84A"

PAGE_MARGIN = "0.85in"
PAGE_BOTTOM_MARGIN = "0.9in"
PAGE_FOOTER_SKIP = "30pt"
NEEDSPACE_TABLE = r"5\baselineskip"
NEEDSPACE_CHAPTER = r"8\baselineskip"
NEEDSPACE_SECTION = r"5\baselineskip"
TABLE_COLUMN_PADDING = "6pt"
TABLE_ARRAY_STRETCH = 1.12
TABLE_EXTRA_ROW_HEIGHT = "0.6pt"
TABLE_ROW_VERTICAL_PADDING = "4pt"
LONGTABLE_PRE_SKIP = "0pt"
LONGTABLE_POST_SKIP = "6pt"


def longtable_begin(
    column_spec: str,
    header_rows: Sequence[str],
    caption: str = "",
    body: str = "",
    foot_rows: Iterable[str] = (),
) -> str:
    """Build a longtable with first-page, repeated, and footer sections."""
    padded_headers = []
    for row in header_rows:
        row = row.rstrip()
        if row.endswith(r"\\"):
            row += "[" + TABLE_ROW_VERTICAL_PADDING + "]"
        padded_headers.append(row)
    header = "\n".join(padded_headers)
    caption_tex = (r"\caption{" + caption + r"}\\" + "\n") if caption else ""
    footer = "\n".join(foot_rows)
    return (
        r"\begin{longtable}{" + column_spec + "}\n"
        + caption_tex
        + r"\hline" + "\n"
        + header + "\n"
        + r"\hline" + "\n"
        + r"\endfirsthead" + "\n"
        + r"\hline" + "\n"
        + header + "\n"
        + r"\hline" + "\n"
        + r"\endhead" + "\n"
        + footer + ("\n" if footer else "")
        + r"\endfoot" + "\n"
        + r"\endlastfoot" + "\n"
        + body
        + ("" if body.endswith("\n") or not body else "\n")
        + r"\end{longtable}"
    )


def repeat_longtable_headers(tex: str) -> str:
    """Add repeated headings to legacy longtables with a recognizable header row."""
    cursor = 0
    result = []
    begin_token = r"\begin{longtable}{"
    end_token = r"\end{longtable}"

    while True:
        start = tex.find(begin_token, cursor)
        if start < 0:
            result.append(tex[cursor:])
            break
        result.append(tex[cursor:start])

        spec_start = start + len(begin_token) - 1
        depth = 0
        spec_end = spec_start
        for spec_end in range(spec_start, len(tex)):
            if tex[spec_end] == "{":
                depth += 1
            elif tex[spec_end] == "}":
                depth -= 1
                if depth == 0:
                    spec_end += 1
                    break
        if depth != 0:
            result.append(tex[start:])
            break

        table_end = tex.find(end_token, spec_end)
        if table_end < 0:
            result.append(tex[start:])
            break

        block = tex[start:table_end]
        if r"\endfirsthead" not in block or r"\endhead" not in block:
            first_rule = block.find(r"\hline", spec_end - start)
            if first_rule >= 0:
                header_start = first_rule + len(r"\hline")
                next_rule = block.find(r"\hline", header_start)
                if next_rule >= 0:
                    header = block[header_start:next_rule].strip()
                    if r"\textbf" in header and r"\\" in header:
                        repeated = (
                            "\n" + r"\endfirsthead" + "\n"
                            + r"\hline" + "\n" + header + "\n"
                            + r"\hline" + "\n" + r"\endhead" + "\n"
                            + r"\endfoot" + "\n" + r"\endlastfoot"
                        )
                        block = block[:next_rule + len(r"\hline")] + repeated + block[next_rule + len(r"\hline"):]

        if r"\multirow" in block:
            block = re.sub(
                r"(\\\\)(\[[^\]]+\])?(\s*\\cline)",
                lambda match: match.group(1) + "*"
                + (match.group(2) or "") + match.group(3),
                block,
            )

        result.append(block)
        result.append(end_token)
        cursor = table_end + len(end_token)

    return "".join(result)
