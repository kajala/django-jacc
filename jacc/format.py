from typing import List


def align_lines(lines: list, column_separator: str = "|") -> List[str]:
    """
    Pads lines so that all rows in single column match. Columns separated by '|' in every line.
    :param lines: list of lines
    :param column_separator: column separator. default is '|'
    :return: list of lines
    """
    rows = []
    col_len: List[int] = []
    for line in lines:
        line = str(line)
        cols = []
        for col_index, col in enumerate(line.split(column_separator)):
            col = str(col).strip()
            cols.append(col)
            if col_index >= len(col_len):
                col_len.append(0)
            col_len[col_index] = max(col_len[col_index], len(col))
        rows.append(cols)

    lines_out: List[str] = []
    for row in rows:
        cols_out = []
        for col_index, col in enumerate(row):
            if col_index == 0:
                col = col.ljust(col_len[col_index])
            else:
                col = col.rjust(col_len[col_index])
            cols_out.append(col)
        lines_out.append(" ".join(cols_out))
    return lines_out
