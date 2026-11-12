"""Editing one small piece of a YAML profile without wrecking the rest of it.

The web page changes one thing at a time: the calculation method, one speaker
entry, the clip that plays at Fajr. The obvious way to do that is
`yaml.safe_load` then `yaml.dump`, and the obvious way is wrong: a round-trip
keeps the data and throws away every comment in the file, and in a starter
profile the comments *are* the documentation - they are where someone who has
never seen the format learns that `isha_interval` exists.

So these helpers work on the text. They locate the top-level block named in the
request, rewrite that block (or one entry inside it), and hand back a file whose
other lines are byte-for-byte what they were, including the comments and the
blank lines between sections.

The safety net is not here: it is the caller. Anything produced by these
functions goes through `load_profile` before it reaches the file (see
`web.WebPanel.save_config`), so a mistake in this module surfaces as a visible
"that is not valid" reply, never as a profile the daemon refuses to start with.
"""
from __future__ import annotations

import re
from typing import Iterable, Optional, Sequence

import yaml

# A top-level mapping key: `method:` at column zero. Comments and blank lines are
# not keys, which is what keeps a `# events` heading attached to the section below
# it rather than being swallowed by the section above.
_TOP_KEY = re.compile(r"^(?P<key>[A-Za-z_][A-Za-z0-9_-]*):(\s|$)")
# A block-sequence entry, at whatever indent the sequence happens to live at.
_ENTRY = re.compile(r"^(?P<indent>[ \t]*)-(?P<rest>([ \t].*)?)$")


def _split(text):
    return text.split("\n")


def find_block(text, key):
    """The LAST top-level match wins, which is what PyYAML means."""
    lines = _split(text)
    hit = None
    for i, line in enumerate(lines):
        match = _TOP_KEY.match(line)
        if not match or match.group("key").strip("\"'") != key:
            continue
        end = i + 1
        j = i + 1
        while j < len(lines):
            line = lines[j]
            if line[:1] in (" ", "\t") or line.startswith("-"):
                end = j + 1
            elif not line.strip():
                pass
            else:
                break
            j += 1
        hit = (i, end)
    return hit


def block_lines(text: str, key: str) -> Optional[list[str]]:
    """The lines under a top-level key, without the `key:` line itself."""
    found = find_block(text, key)
    if found is None:
        return None
    start, end = found
    return _split(text)[start + 1:end]


def set_block(text, key, new_lines):
    """Keep the comment that sat behind `key:` on the key line."""
    found = find_block(text, key)
    lines = _split(text)
    head = lines[found[0]] if found else f"{key}:"
    tail = _TRAILING.search(head)
    header = f"{key}:" + (tail.group(1).rstrip() if tail else "")
    if found is None:
        body = text.rstrip("\n")
        added = "\n\n" + header
        for line in new_lines:
            added += "\n" + line
        return body + added + "\n"
    start, end = found
    return "\n".join(lines[:start] + [header] + list(new_lines) + lines[end:])


def entries(text, key):
    """An entry's span stops before the blank lines and comments that
    introduce the next entry, the way find_block does for whole blocks."""
    found = find_block(text, key)
    if found is None:
        return []
    start, end = found
    lines = _split(text)
    starts = []
    indent = None
    for j in range(start + 1, end):
        match = _ENTRY.match(lines[j])
        if not match:
            continue
        if indent is None:
            indent = match.group("indent")
            starts.append(j)
        elif match.group("indent") == indent:
            starts.append(j)
    out = []
    for n, s in enumerate(starts):
        stop = starts[n + 1] if n + 1 < len(starts) else end
        while stop > s + 1 and (not lines[stop - 1].strip()
                                or lines[stop - 1].lstrip(" \t").startswith("#")):
            stop -= 1
        body = "\n".join(lines[s:stop])
        out.append({"index": n, "start": s, "end": stop,
                    "name": entry_scalar(body, "name") or entry_scalar(body, "at"),
                    "text": body})
    return out


def _key_indent(entry_text):
    """A comment line inside an entry does not set the key column."""
    lines = entry_text.split("\n")
    first = lines[0]
    match = _ENTRY.match(first)
    base = len(match.group("indent")) if match else 0
    for line in lines[1:]:
        if line.strip() and not line.lstrip(" \t").startswith("#"):
            return len(line) - len(line.lstrip(" \t"))
    return base + 2


def _own_field_lines(text: str, key: str) -> Optional[list[str]]:
    """The lines setting fields directly on `key`, and not on something inside it.

    Indentation is the only thing that tells those apart, and counting a nested
    `dhuhr:` as a knob of `method:` would tell a person their timetable had an
    override they never wrote. None means there is no such block at all.
    """
    if find_block(text, key) is None:
        return None
    lines = block_lines(text, key) or []
    column = None
    for line in lines:
        if line.strip() and not line.lstrip(" \t").startswith("#"):
            column = len(line) - len(line.lstrip(" \t"))
            break
    if column is None:
        return []
    return [line for line in lines
            if line.strip() and not line.lstrip(" \t").startswith("#")
            and len(line) - len(line.lstrip(" \t")) == column]


def block_fields(text: str, key: str) -> list[str]:
    """Which fields a mapping block actually sets (a commented-out hint is not set)."""
    out = []
    for line in _own_field_lines(text, key) or []:
        match = re.match(r"^([A-Za-z_][A-Za-z0-9_-]*):(\s|$)", line.strip())
        if match:
            out.append(match.group(1))
    return out


def block_value(text: str, key: str, field: str) -> Optional[str]:
    """Read one field of a block, whether the block is written as lines or on one line.

    `method:` may be a block of knobs or the one-line map `muezzin init` used to
    write, and the page has to know which preset is in force either way.
    """
    found = find_block(text, key)
    if found is None:
        return None
    head = _split(text)[found[0]].split(":", 1)[1].strip()
    if head.startswith("{"):
        try:
            parsed = yaml.safe_load("\n".join(_split(text)[found[0]:found[1]])) or {}
        except yaml.YAMLError:
            return None
        value = (parsed.get(key) or {}).get(field)
        return None if value is None else str(value)
    for line in _own_field_lines(text, key) or []:
        name, _, rest = line.strip().partition(":")
        if name == field:
            return _value_of(rest)
    return None


_TRAILING = re.compile(r"([ \t]+#.*)$")


def set_in_block(text, key, edits):
    """Only the block's own lines are fields of the block, and a field name may be quoted."""
    found = find_block(text, key)
    if not found:
        raise ValueError(f"the file has no {key}: section to write into")
    start, end = found
    lines = text.splitlines(keepends=True)
    inline = lines[start].split(":", 1)[1].strip()
    if inline.startswith("{"):
        try:
            parsed = yaml.safe_load(lines[start])
        except yaml.YAMLError as exc:
            raise ValueError(f"{key}: is written on one line but does not parse: {exc}")
        inner = parsed.get(key) if isinstance(parsed, dict) else None
        if not isinstance(inner, dict):
            raise ValueError(f"{key}: is not a set of fields on its line")
        inner.update(edits)
        body = yaml.safe_dump(inner, default_flow_style=True, sort_keys=False,
                              width=10 ** 6).strip()
        lines[start] = f"{key}: {body}" + ("\n" if lines[start].endswith("\n") else "")
        return "".join(lines)
    indent = "  "
    for i in range(start + 1, end):
        stripped = lines[i].strip()
        if stripped and not stripped.startswith("#"):
            lead = lines[i][: len(lines[i]) - len(lines[i].lstrip())]
            indent = lead or "  "
            break
    for field, value in edits.items():
        hit = hint = None
        for i in range(start + 1, end):
            line = lines[i]
            lead = len(line) - len(line.lstrip(" \t"))
            if lead != len(indent):
                continue                       # nested lines belong to the block below
            body = line.lstrip(" \t")
            commented = body.startswith("#")
            probe = body[1:].lstrip(" \t") if commented else body
            if not re.match(_kpat(field) + r":(\s|$)", probe):
                continue
            if commented:
                if hint is None:
                    hint = i
            else:
                hit = i
                break
        note = ""
        if hit is not None:
            tail = _TRAILING.search(lines[hit].rstrip("\r\n"))
            note = tail.group(1).rstrip() if tail else ""
            lines[hit] = f"{indent}{field}: {scalar(value)}{note}\n"
        elif hint is not None:
            lines.insert(hint, f"{indent}{field}: {scalar(value)}\n")
            end += 1
        else:
            lines.insert(start + 1, f"{indent}{field}: {scalar(value)}\n")
            end += 1
    return "".join(lines)


def set_scalar(text, key, value):
    """Keep the trailing comment, the way set_in_block already does."""
    found = find_block(text, key)
    lines = _split(text)
    if found is not None:
        start, end = found
        if end > start + 1:
            raise ValueError(f"{key}: is a whole section, not a single value")
        tail = _TRAILING.search(lines[start])
        note = tail.group(1).rstrip() if tail else ""
        return "\n".join(lines[:start] + [f"{key}: {scalar(value)}{note}"]
                         + lines[start + 1:])
    tail_nl = "\n" if text.endswith("\n") else ""
    return text.rstrip("\n") + f"\n\n{key}: {scalar(value)}" + tail_nl


def _field_re(field, column=None):
    if column is None:
        return re.compile(r"^[ \t]*(?:-[ \t]+)?" + _kpat(field) + r":(\s|$)")
    return re.compile(r"^(?P<pre>[ \t]*(?:-[ \t]+)?)" + _kpat(field) + r":(\s|$)")


def _entry_text(entry) -> str:
    """Accept either the text of an entry or the row `entries()` handed back.

    Callers work with rows, and making every one of them remember to write
    `row["text"]` is a bug factory that would only show up on the rare path.
    """
    return entry["text"] if isinstance(entry, dict) else str(entry)


def _value_of(raw: str) -> Optional[str]:
    """One scalar from the text after `field:`, quoting and comments undone.

    The comment matters more than it looks: in the starter profile the line is
    `target: Kitchen speaker   # muezzin devices lists names`, and a reader that
    kept the comment would go looking for a speaker called "Kitchen speaker #
    muezzin devices lists names" and never find one.
    """
    raw = raw.strip()
    if not raw:
        return None
    if raw[0] in ("\"", "'"):
        quote, i = raw[0], 1
        while i < len(raw):
            if raw[i] == "\\":
                i += 2
                continue
            if raw[i] == quote:
                return raw[1:i]
            i += 1
        return strip_quotes(raw)          # unterminated: give back what is there
    return re.split(r"\s+#", raw, maxsplit=1)[0].strip() or None


def entry_scalar(entry, key):
    text = _entry_text(entry)
    column = _key_indent(text)
    for line in text.split("\n"):
        m = re.match(r"^(?P<pre>[ \t]*(?:-[ \t]+)?)" + _kpat(key) + r":[ \t]*(?P<val>.*)$", line)
        if m and len(m.group("pre")) == column:
            return _value_of(m.group("val"))
    return None


def entry_list(entry, key):
    """A flow list is read by yaml, not split on commas."""
    lines = _entry_text(entry).split("\n")
    column = _key_indent(_entry_text(entry))
    for i, line in enumerate(lines):
        m = re.match(r"^(?P<pre>[ \t]*(?:-[ \t]+)?)" + _kpat(key) + r":[ \t]*(.*)$", line)
        if not m or len(m.group("pre")) != column:
            continue
        own = column
        rest = m.group(2).strip()
        if rest.startswith("["):
            try:
                parsed = yaml.safe_load(rest)
            except yaml.YAMLError:
                parsed = None
            if isinstance(parsed, list):
                return [str(v) for v in parsed if v not in (None, "")]
            return []
        out = []
        deeper = None
        for following in lines[i + 1:]:
            if not following.strip() or following.lstrip(" \t").startswith("#"):
                continue
            col = len(following) - len(following.lstrip(" \t"))
            if following.lstrip(" \t").startswith("- "):
                if deeper is None:
                    deeper = col
                elif col != deeper:
                    break
                value = _value_of(following.strip()[2:])
                if value:
                    out.append(value)
            elif col > own:
                continue
            else:
                break
        return out
    return None


def strip_quotes(value: str) -> str:
    value = value.strip()
    if value[:1] in "\"'" and value[-1:] == value[:1] and len(value) > 1:
        return value[1:-1]
    return value


# words a YAML reader turns into a boolean or a null, and shapes that read back
# as numbers: either one leaving here bare means the next read gets a different
# value than the one that went in, which is the sort of change nobody notices.
_YAML_WORDS = re.compile(r"y|yes|n|no|true|false|on|off|null", re.IGNORECASE)
_LOOKS_LIKE_A_NUMBER = re.compile(r"[+-]?(?:\d[\d_]*\.?[\d_]*(?:[eE][+-]?\d+)?|\.\d+)")


def scalar(value) -> str:
    """Render a scalar the way a person would have typed it where possible.

    Plain for the boring cases, JSON quoting otherwise, because a JSON string is
    a valid YAML double-quoted scalar and it keeps `volume: 0.35` looking like a
    number rather than a word.
    """
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    text = str(value)
    if (re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.\- /]*", text)
            and text == text.strip()
            and not _YAML_WORDS.fullmatch(text)
            and not _LOOKS_LIKE_A_NUMBER.fullmatch(text)):
        return text
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def flow(values: Iterable[str]) -> str:
    return "[" + ", ".join(scalar(v) for v in values) + "]"


def edit_entry(text, key, index, edits, add_comment=None):
    rows = entries(text, key)
    if not 0 <= index < len(rows):
        raise IndexError("no such entry")
    row = rows[index]
    indent = " " * _key_indent(row["text"])
    column = _key_indent(row["text"])
    out = row["text"].split("\n")
    for field, value in edits.items():
        rendered = flow(value) if isinstance(value, (list, tuple)) else scalar(value)
        hit = next((i for i, line in enumerate(out) if _at(line, field, column)), None)
        if hit is None:
            out.append(f"{indent}{field}: {rendered}"
                       + (f"  # {add_comment}" if add_comment else ""))
        else:
            dash = re.match(r"^([ \t]*)-[ \t]+", out[hit])
            prefix = dash.group(1) + "- " if dash else indent
            out[hit] = f"{prefix}{field}: {rendered}"
            if isinstance(value, (list, tuple)):
                while hit + 1 < len(out) and out[hit + 1].lstrip().startswith("- "):
                    del out[hit + 1]
    lines = _split(text)
    return "\n".join(lines[:row["start"]] + out + lines[row["end"]:])


def _entry_lines(fields: dict, comment: Optional[str] = None) -> list[str]:
    """One entry, written the way a person would: dash on the first field."""
    lines = []
    if comment:
        lines.append("# " + comment)
    for i, (field, value) in enumerate(fields.items()):
        rendered = flow(value) if isinstance(value, (list, tuple)) else scalar(value)
        lines.append(f"{'- ' if i == 0 else '  '}{field}: {rendered}")
    return lines


def _indented(lines: list[str], prefix: str) -> list[str]:
    return [prefix + line if line.strip() else line for line in lines]


def append_entry(text: str, key: str, fields: dict, comment: Optional[str] = None) -> str:
    """Add one entry to the end of a top-level list, matching the file's style.

    The new entry goes after the last existing one and is given that entry's dash
    indentation, so a profile written with two spaces keeps its two spaces.
    """
    rows = entries(text, key)
    lines = _split(text)
    found = find_block(text, key)
    if found is not None and lines[found[0]].split(":", 1)[1].strip().startswith("["):
        # `events: [ {name: ...}, ... ]` on one line: the entry could only be
        # added by unpicking that line, and silently re-writing a whole section
        # the person formatted themselves is not a small thing to do unsolved.
        raise ValueError(f"{key}: is written on one line; write it with one entry per "
                         f"line (the layout `muezzin init` gives you) to change it here")
    body = _entry_lines(fields, comment)
    if rows:
        dash = _ENTRY.match(rows[0]["text"].split("\n")[0])
        body = _indented(body, dash.group("indent") if dash else "")
        insert_at = rows[-1]["end"]
        # Slide above the blank line that trails the block, so the new entry does
        # not land between the last entry and the comment heading the next section.
        while insert_at > rows[-1]["start"] and not lines[insert_at - 1].strip():
            insert_at -= 1
        return "\n".join(lines[:insert_at] + body + lines[insert_at:])
    body = _indented(body, "  ")
    if found is None:
        tail = "\n" if text.endswith("\n") else ""
        return text.rstrip("\n") + f"\n\n{key}:\n" + "\n".join(body) + tail
    start, end = found
    return "\n".join(lines[:end] + body + lines[end:])


def delete_entry(text, key, index):
    rows = entries(text, key)
    if not 0 <= index < len(rows):
        raise IndexError("no such entry")
    row = rows[index]
    lines = _split(text)
    start, end = row["start"], row["end"]
    while end < len(lines) and not lines[end].strip():
        end += 1
    return "\n".join(lines[:start] + lines[end:])

def _at(line, field, column):
    """The field name must start at `column`, not at any indent."""
    m = re.match(r"^(?P<pre>[ \t]*(?:-[ \t]+)?)" + _kpat(field) + r":(\s|$)", line)
    if not m:
        return None
    return m if len(m.group("pre")) == column else None



def _kpat(field):
    """A field name may be quoted in the file."""
    return r"[\"']?" + re.escape(field) + r"[\"']?"


