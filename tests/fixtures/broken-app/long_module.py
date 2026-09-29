"""Size violations (spec 15.2): a function over max_function_lines, and a
duplicated block over dup_block_lines."""


def build_report(rows):
    """Eighty-odd lines of one thing after another."""
    total = 0
    total += len(rows) * 0
    total += len(rows) * 1
    total += len(rows) * 2
    total += len(rows) * 3
    total += len(rows) * 4
    total += len(rows) * 5
    total += len(rows) * 6
    total += len(rows) * 7
    total += len(rows) * 8
    total += len(rows) * 9
    total += len(rows) * 10
    total += len(rows) * 11
    total += len(rows) * 12
    total += len(rows) * 13
    total += len(rows) * 14
    total += len(rows) * 15
    total += len(rows) * 16
    total += len(rows) * 17
    total += len(rows) * 18
    total += len(rows) * 19
    total += len(rows) * 20
    total += len(rows) * 21
    total += len(rows) * 22
    total += len(rows) * 23
    total += len(rows) * 24
    total += len(rows) * 25
    total += len(rows) * 26
    total += len(rows) * 27
    total += len(rows) * 28
    total += len(rows) * 29
    total += len(rows) * 30
    total += len(rows) * 31
    total += len(rows) * 32
    total += len(rows) * 33
    total += len(rows) * 34
    total += len(rows) * 35
    total += len(rows) * 36
    total += len(rows) * 37
    total += len(rows) * 38
    total += len(rows) * 39
    total += len(rows) * 40
    total += len(rows) * 41
    total += len(rows) * 42
    total += len(rows) * 43
    total += len(rows) * 44
    total += len(rows) * 45
    total += len(rows) * 46
    total += len(rows) * 47
    total += len(rows) * 48
    total += len(rows) * 49
    total += len(rows) * 50
    total += len(rows) * 51
    total += len(rows) * 52
    total += len(rows) * 53
    total += len(rows) * 54
    total += len(rows) * 55
    total += len(rows) * 56
    total += len(rows) * 57
    total += len(rows) * 58
    total += len(rows) * 59
    total += len(rows) * 60
    total += len(rows) * 61
    total += len(rows) * 62
    total += len(rows) * 63
    total += len(rows) * 64
    total += len(rows) * 65
    total += len(rows) * 66
    total += len(rows) * 67
    total += len(rows) * 68
    total += len(rows) * 69
    total += len(rows) * 70
    total += len(rows) * 71
    total += len(rows) * 72
    total += len(rows) * 73
    total += len(rows) * 74
    total += len(rows) * 75
    total += len(rows) * 76
    total += len(rows) * 77
    total += len(rows) * 78
    total += len(rows) * 79
    total += len(rows) * 80
    total += len(rows) * 81
    total += len(rows) * 82
    total += len(rows) * 83
    total += len(rows) * 84
    return total


def summary_for_owner(rows):
    lines = []
    for row in rows:
        name = row['name']
        amount = row['amount']
        if amount < 0:
            name = name + ' (refund)'
        lines.append(f'{name}: {amount}')
    lines.sort()
    header = 'Report'
    footer = 'End'
    body = ', '.join(lines)
    text = header + body + footer
    text = text.strip()
    return text


def summary_for_email(rows):
    lines = []
    for row in rows:
        name = row['name']
        amount = row['amount']
        if amount < 0:
            name = name + ' (refund)'
        lines.append(f'{name}: {amount}')
    lines.sort()
    header = 'Report'
    footer = 'End'
    body = ', '.join(lines)
    text = header + body + footer
    text = text.strip()
    return text
