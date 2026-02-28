#!/usr/bin/env python3
"""Fix alignment of box-drawing ASCII art in markdown files.

Korean (Hangul) characters are 2 display-columns wide in monospace fonts.
The original author counted them as 1 column, so lines with Korean have
too many trailing spaces, pushing the right border too far right.

Fix strategy (right-border only)
---------------------------------
For each line in a box, adjust trailing spaces before the last ║/│ so
that dw(line) == target display width (from the box's top/bottom border).

Side-by-side layout  (│ content │    │ content │)
-------------------------------------------------
Split each content line DYNAMICALLY by locating the gap pattern
  │<N spaces>│   (N determined from a Korean-free reference line)
then fix each half's right border independently.

We read the display-width target from a Korean-free reference line in
the block (typically the bottom border └───┘).
"""

import unicodedata
import sys


# ── display-width helpers ─────────────────────────────────────────────────

def char_width(ch):
    cp = ord(ch)
    if cp < 0x7F:
        return 1
    if 0xAC00 <= cp <= 0xD7AF:                         # Hangul syllables
        return 2
    if 0x1100 <= cp <= 0x11FF or 0x3130 <= cp <= 0x318F or 0xA960 <= cp <= 0xA97F:
        return 2
    if 0x4E00 <= cp <= 0x9FFF or 0x3400 <= cp <= 0x4DBF or 0xF900 <= cp <= 0xFAFF:
        return 2
    if 0xFF01 <= cp <= 0xFF60 or 0xFFE0 <= cp <= 0xFFE6:
        return 2
    if 0x2500 <= cp <= 0x259F:                          # box-drawing / block elements
        return 1
    if cp >= 0x10000:                                   # supplementary (emoji)
        return 2
    eaw = unicodedata.east_asian_width(ch)
    if eaw in ('W', 'F'):
        return 2
    return 1


def dw(s):
    return sum(char_width(c) for c in s)


def has_wide(s):
    return any(char_width(c) > 1 for c in s)


# ── core fix ─────────────────────────────────────────────────────────────

def fix_right_border(s, target):
    """Adjust trailing spaces before the last ║/│ to reach target display width.
    When content is too wide, trims spaces from rightmost 2+ space runs.
    Returns s unchanged if last char is not ║/│.
    """
    s = s.rstrip()
    if not s:
        return s
    last = s[-1]
    if last not in ('║', '│'):
        return s
    content = s[:-1].rstrip(' ')
    need = target - dw(content) - 1  # 1 for the border char
    if need < 0:
        # Content too wide: trim from rightmost 2+ space runs (keep ≥1 space each)
        excess = -need
        chars = list(content)
        i = len(chars) - 1
        while i >= 0 and excess > 0:
            if chars[i] == ' ':
                run_end = i
                run_start = i
                while run_start > 0 and chars[run_start - 1] == ' ':
                    run_start -= 1
                run_len = run_end - run_start + 1
                if run_len >= 2:
                    can_remove = min(excess, run_len - 1)
                    del chars[run_end - can_remove + 1:run_end + 1]
                    excess -= can_remove
                    i = run_start - 1
                else:
                    i -= 1
            else:
                i -= 1
        content = ''.join(chars)
        need = target - dw(content) - 1
        if need < 0:
            need = 0
    return content + ' ' * need + last


# ── block classification ──────────────────────────────────────────────────

CLOSE_CHARS = frozenset('│║┘╝┐╗┤╣')
OPEN_CHARS  = frozenset('│║└╚┌╔├╠')
CLOSE_FINAL = frozenset('╗┐╝┘╣┤')   # lines ending with these: pure border, skip


def is_side_by_side(lines):
    """Return True ONLY if the TOP BORDER line (starting with ┌ or ╔)
    itself contains two box patterns: e.g. ┌───┐    ┌───┐
    This avoids false positives from nested mini-boxes or flowcharts.
    """
    for ln in lines:
        s = ln.rstrip()
        if not s:
            continue
        # Only the first non-empty line matters.
        # If it doesn't start with ┌ or ╔, this isn't a recognisable box.
        if s[0] not in ('┌', '╔'):
            return False
        # Look for: close_corner + (1+ spaces) + open_corner
        for i, ch in enumerate(s):
            if ch in ('┐', '╗') and i > 0:
                rest = s[i + 1:]
                stripped = rest.lstrip(' ')
                if rest != stripped and stripped and stripped[0] in ('┌', '╔'):
                    return True
        return False  # First border line analysed, not side-by-side
    return False


def find_clean_line(lines):
    """Return the first line in the block that contains no wide characters
    and ends with a box-border character.  Used to determine display-width
    targets and gap sizes.
    """
    for ln in lines:
        s = ln.rstrip()
        if not s:
            continue
        if not has_wide(s) and len(s) > 1 and s[-1] in CLOSE_FINAL | frozenset('║│'):
            return s
    return None


def find_sbs_gap(lines):
    """For a side-by-side block, find (gap_char_len, left_dw, right_dw)
    using a Korean-free reference line (bottom border preferred).
    Returns None if not found.
    """
    for ln in lines:
        s = ln.rstrip()
        if not s or has_wide(s):
            continue
        # Scan for: close_char + spaces + open_char
        for i, ch in enumerate(s):
            if i == 0 or ch not in CLOSE_CHARS:
                continue
            j = i + 1
            while j < len(s) and s[j] == ' ':
                j += 1
            if j == i + 1:          # no spaces
                continue
            if j < len(s) and s[j] in OPEN_CHARS:
                gap_n = j - i - 1
                left_part  = s[:i+1]
                right_part = s[j:]
                return gap_n, dw(left_part), dw(right_part)
    return None


def split_line_sbs(s, gap_n):
    """Dynamically find the mid-gap in a side-by-side content line.
    Searches for: (close_char)(gap_n spaces)(open_char)  at position > 0.
    Returns (left, gap_str, right) or None.
    """
    gap_str = ' ' * gap_n
    for i in range(1, len(s)):
        if s[i] not in CLOSE_CHARS:
            continue
        end = i + 1 + gap_n
        if end >= len(s):
            continue
        if s[i+1:end] == gap_str and s[end] in OPEN_CHARS:
            return s[:i+1], gap_str, s[end:]
    return None


# ── block processors ─────────────────────────────────────────────────────

def find_target_dw(lines):
    """Return display width from the first full box-border line (no Korean)."""
    for ln in lines:
        s = ln.rstrip()
        if not s or has_wide(s) or len(s) < 2:
            continue
        if (s[0] in '╔┌' and s[-1] in '╗┐') or \
           (s[0] in '╚└' and s[-1] in '╝┘') or \
           (s[0] in '╠├' and s[-1] in '╣┤'):
            return dw(s)
    return None


def process_single_box(lines):
    target = find_target_dw(lines)
    if target is None:
        return lines, False

    modified = False
    result = []
    for ln in lines:
        s = ln.rstrip()
        if not s:
            result.append(ln)
            continue
        last = s[-1]
        if last in CLOSE_FINAL:
            result.append(ln)
            continue
        if last not in ('║', '│'):
            result.append(ln)
            continue
        if dw(s) == target:
            result.append(ln)
            continue
        fixed = fix_right_border(s, target)
        if fixed != s:
            modified = True
        result.append(fixed + '\n')
    return result, modified


def process_side_by_side(lines):
    sbs = find_sbs_gap(lines)
    if sbs is None:
        # Fallback: treat as single box
        return process_single_box(lines)

    gap_n, left_target, right_target = sbs

    modified = False
    result = []
    for ln in lines:
        s = ln.rstrip()
        if not s:
            result.append(ln)
            continue

        # Try to split the line at the mid-gap
        split = split_line_sbs(s, gap_n)
        if split is None:
            # Can't find the gap — leave the line as-is
            result.append(ln)
            continue

        left_raw, gap_str, right_raw = split

        # Fix left half
        left_last = left_raw[-1] if left_raw else ''
        if left_last in CLOSE_FINAL:
            left_fixed = left_raw     # pure border; already correct
        elif left_last in ('│', '║') and dw(left_raw) != left_target:
            left_fixed = fix_right_border(left_raw, left_target)
            if left_fixed != left_raw:
                modified = True
        else:
            left_fixed = left_raw

        # Fix right half
        right_last = right_raw[-1] if right_raw else ''
        if right_last in CLOSE_FINAL:
            right_fixed = right_raw   # pure border; already correct
        elif right_last in ('│', '║') and dw(right_raw) != right_target:
            right_fixed = fix_right_border(right_raw, right_target)
            if right_fixed != right_raw:
                modified = True
        else:
            right_fixed = right_raw

        reconstructed = left_fixed + gap_str + right_fixed
        result.append(reconstructed + '\n')

    return result, modified


def process_block(block_lines):
    all_text = ''.join(block_lines)
    if not any(ch in all_text for ch in '╔╗╚╝║╠╣┌┐└┘├┤'):
        return block_lines, False

    if is_side_by_side(block_lines):
        return process_side_by_side(block_lines)
    else:
        return process_single_box(block_lines)


# ── main ─────────────────────────────────────────────────────────────────

def main():
    filepath = sys.argv[1]
    with open(filepath, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    result = []
    in_code = False
    block = []
    blocks_fixed = 0
    lines_changed = 0

    for line in lines:
        if line.strip().startswith('```'):
            if not in_code:
                in_code = True
                block = []
                result.append(line)
            else:
                fixed_block, was_modified = process_block(block)
                if was_modified:
                    blocks_fixed += 1
                    for orig, fixed in zip(block, fixed_block):
                        if orig.rstrip('\n') != fixed.rstrip('\n'):
                            lines_changed += 1
                result.extend(fixed_block)
                result.append(line)
                in_code = False
        elif in_code:
            block.append(line)
        else:
            result.append(line)

    with open(filepath, 'w', encoding='utf-8') as f:
        f.writelines(result)

    print(f"Fixed {lines_changed} lines across {blocks_fixed} code blocks")


if __name__ == '__main__':
    main()
