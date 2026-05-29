"""Build Obsidian wiki pages from graphify-out/graph.json, with short per-symbol summaries."""

import json
import os
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
GRAPH_PATH = REPO_ROOT / "graphify-out" / "graph.json"
OUTPUT_DIR = REPO_ROOT / "obsidian_vault"


def safe_note_stem(node_id: str) -> str:
    """Map graph node id to a Windows-safe Obsidian note filename stem (no .md)."""
    s = str(node_id)
    for ch in '<>:"/\\|?*':
        s = s.replace(ch, "_")
    s = s.strip(" .")
    return s or "unnamed"


def parse_line_ref(loc: str) -> int:
    if not loc or not str(loc).startswith("L"):
        return 1
    return int(loc[1:])


def humanize_label(label: str) -> str:
    label = label.strip()
    if label.endswith("()"):
        label = label[:-2]
    parts = re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?=[A-Z][a-z]|\b)", label)
    if not parts:
        return f"Code symbol `{label}`."
    words = [parts[0].lower()] + [p.lower() for p in parts[1:]]
    sentence = " ".join(words)
    return sentence[0].upper() + sentence[1:] + "." if len(sentence) > 1 else sentence.upper() + "."


def extract_python_module_docstring(lines: list[str]) -> str | None:
    i = 0
    while i < len(lines) and (lines[i].strip().startswith("#") or not lines[i].strip()):
        i += 1
    if i >= len(lines):
        return None
    block: list[str] = []
    first = lines[i].lstrip()
    if not first.startswith('"""'):
        return None
    if first.count('"""') >= 2 and len(first.strip()) > 6:
        inner = first.split('"""', 2)[1].strip()
        return trim_summary(inner) if inner else None
    block.append(lines[i])
    i += 1
    while i < len(lines) and '"""' not in lines[i]:
        block.append(lines[i])
        i += 1
    if i < len(lines):
        block.append(lines[i])
    text = "".join(block)
    inner = text.split('"""', 2)[1] if '"""' in text else ""
    inner = inner.split('"""')[0].strip()
    return trim_summary(inner) if inner else None


def extract_first_module_jsdoc(lines: list[str]) -> str | None:
    text = "\n".join(lines[:80])
    m = re.search(r"/\*\*(.*?)\*/", text, re.DOTALL)
    if not m:
        return None
    inner = m.group(1)
    desc_lines = []
    for line in inner.splitlines():
        s = line.strip()
        if s.startswith("*"):
            s = s[1:].strip()
        if s.startswith("@"):
            break
        if s:
            desc_lines.append(s)
    if not desc_lines:
        return None
    summary = " ".join(desc_lines)
    for sep in ".!?":
        if sep in summary[:200]:
            summary = summary.split(sep)[0] + sep
            break
    return summary.strip()


def trim_summary(s: str) -> str:
    s = re.sub(r"\s+", " ", s).strip()
    if len(s) > 220:
        s = s[:217] + "..."
    return s


def extract_python_function_docstring(lines: list[str], start_line_1based: int) -> str | None:
    def_idx = start_line_1based - 1
    if def_idx < 0 or def_idx >= len(lines):
        return None
    head = lines[def_idx].strip()
    if not (head.startswith("def ") or head.startswith("async def ")):
        return None
    j = def_idx + 1
    while j < len(lines) and lines[j].strip() == "":
        j += 1
    if j >= len(lines):
        return None
    line = lines[j].lstrip()
    if line.startswith('"""'):
        if line.count('"""') >= 2:
            inner = line.split('"""', 2)[1].strip()
            return trim_summary(inner) if inner else None
        block = [lines[j]]
        j += 1
        while j < len(lines) and '"""' not in lines[j]:
            block.append(lines[j])
            j += 1
        if j < len(lines):
            block.append(lines[j])
        text = "".join(block)
        parts = text.split('"""')
        inner = parts[1].strip() if len(parts) > 1 else ""
        return trim_summary(inner) if inner else None
    if line.startswith("#"):
        return trim_summary(line[1:].strip())
    return None


def extract_comment_above_function(lines: list[str], start_line_1based: int) -> str | None:
    """Comment block immediately above the symbol (only blank lines allowed between)."""
    i = start_line_1based - 2
    while i >= 0 and lines[i].strip() == "":
        i -= 1
    if i < 0:
        return None

    s = lines[i].strip()
    if s.startswith("//") and not s.startswith("///"):
        return trim_summary(s[2:].strip())

    closers = ("}", "});", "};")
    if s in closers or (s.startswith("}") and not s.startswith("*/")):
        return None
    if s == ")" or s.endswith(");") and s.startswith(")"):
        return None

    if not (s.endswith("*/") or s.startswith("*") or s.startswith("/**")):
        return None

    block: list[str] = []
    j = i
    while j >= 0:
        line = lines[j]
        block.insert(0, line)
        if "/**" in line:
            break
        j -= 1
    if j < 0 or "/**" not in "\n".join(block):
        return None

    desc_parts: list[str] = []
    for line in block:
        st = line.strip()
        if st.startswith("/**"):
            st = st.replace("/**", "", 1).strip()
        if st.endswith("*/"):
            st = st[:-2].strip()
        if st.startswith("*"):
            st = st[1:].strip()
        if st.startswith("@"):
            continue
        if st:
            desc_parts.append(st)
    if not desc_parts:
        return None
    summary = " ".join(desc_parts)
    for sep in ".!?":
        if sep in summary:
            summary = summary.split(sep)[0] + sep
            break
    return trim_summary(summary)


def describe_node(node: dict, lines_cache: dict[str, list[str]]) -> str:
    label = node.get("label") or ""
    source_file = (node.get("source_file") or "").replace("\\", "/")
    loc = parse_line_ref(node.get("source_location") or "L1")

    if not source_file:
        return humanize_label(label)

    path = REPO_ROOT / source_file
    if not path.is_file():
        return humanize_label(label)

    key = str(path)
    if key not in lines_cache:
        with open(path, encoding="utf-8", errors="replace") as f:
            lines_cache[key] = f.readlines()
    lines = lines_cache[key]

    is_file_node = bool(re.search(r"\.[a-zA-Z0-9]+$", label)) and "(" not in label
    if is_file_node:
        if source_file.endswith(".py"):
            pydoc = extract_python_module_docstring(lines)
            if pydoc:
                return pydoc
        mod = extract_first_module_jsdoc(lines)
        if mod:
            return mod
        return trim_summary(f"Source module `{label}`.")

    if source_file.endswith(".py"):
        py_fn = extract_python_function_docstring(lines, loc)
        if py_fn:
            return py_fn

    summary = extract_comment_above_function(lines, loc)
    if summary:
        return summary

    mod = Path(source_file.replace("\\", "/")).stem
    h = humanize_label(label).rstrip(".")
    return f"{h} ({mod} module)."


def main() -> None:
    with open(GRAPH_PATH, encoding="utf-8") as f:
        data = json.load(f)

    nodes = {node["id"]: node for node in data["nodes"]}
    links = data["links"]

    calls = {k: [] for k in nodes}
    called_by = {k: [] for k in nodes}
    contains = {k: [] for k in nodes}

    for link in links:
        rel = link["relation"]
        if rel == "calls":
            src = link.get("_src") or link["source"]
            tgt = link.get("_tgt") or link["target"]
            calls[src].append(tgt)
            called_by[tgt].append(src)
        elif rel == "contains":
            src = link["source"]
            tgt = link["target"]
            contains[src].append(tgt)

    lines_cache: dict[str, list[str]] = {}
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    for node_id, node in nodes.items():
        stem = safe_note_stem(node_id)
        filename = OUTPUT_DIR / f"{stem}.md"
        what = describe_node(node, lines_cache)

        with open(filename, "w", encoding="utf-8") as f:
            f.write(f"# {node['label']}\n\n")
            f.write("## What it does\n")
            f.write(f"{what}\n\n")
            f.write(f"Type: {node.get('file_type', '')}\n")
            f.write(f"File: {node.get('source_file', '')}\n")
            f.write(f"Graph id: `{node_id}`\n\n")

            if contains[node_id]:
                f.write("## Contains\n")
                for c in contains[node_id]:
                    f.write(f"- [[{safe_note_stem(c)}]]\n")
                f.write("\n")

            if calls[node_id]:
                f.write("## Calls\n")
                for c in calls[node_id]:
                    f.write(f"- [[{safe_note_stem(c)}]]\n")
                f.write("\n")

            if called_by[node_id]:
                f.write("## Called By\n")
                for c in called_by[node_id]:
                    f.write(f"- [[{safe_note_stem(c)}]]\n")
                f.write("\n")

    print("Obsidian vault generated with descriptions:", OUTPUT_DIR)


if __name__ == "__main__":
    main()
