"""Minimal YAML compatibility layer used when PyYAML is unavailable."""
from __future__ import annotations

import json
from typing import Any, List, Optional, Tuple, Union

__all__ = ["safe_load", "load", "safe_dump", "dump"]


class _SimpleYAMLParser:
    """Very small YAML subset parser covering the manifests used in tests."""

    def __init__(self, text: str):
        self.lines: List[str] = text.splitlines()
        self.index: int = 0

    def parse(self) -> Any:
        data = self._parse_mapping(0)
        # Consume any trailing blank/comment lines
        while True:
            peek = self._peek()
            if peek is None:
                break
            indent, stripped, _ = peek
            if not stripped or stripped.startswith("#"):
                self.index += 1
                continue
            raise ValueError("unexpected content after document end")
        return data

    def _peek(self) -> Optional[Tuple[int, str, int]]:
        idx = self.index
        while idx < len(self.lines):
            raw = self.lines[idx]
            stripped = raw.strip()
            if not stripped:
                idx += 1
                continue
            if stripped.startswith("#"):
                idx += 1
                continue
            indent = len(raw) - len(raw.lstrip(" "))
            return indent, stripped, idx
        return None

    def _advance_to(self, target_index: int) -> None:
        if target_index < self.index:
            raise ValueError("internal parser error: cannot rewind")
        self.index = target_index

    def _split_key_value(self, text: str) -> Tuple[str, str]:
        if ":" not in text:
            raise ValueError(f"expected ':' in mapping entry: {text}")
        key, value = text.split(":", 1)
        return key.strip(), value.strip()

    def _parse_mapping(self, indent: int) -> dict[str, Any]:
        result: dict[str, Any] = {}
        while True:
            peek = self._peek()
            if peek is None:
                break
            current_indent, stripped, idx = peek
            if current_indent < indent:
                break
            if current_indent > indent:
                raise ValueError("unexpected increased indent in mapping")
            self._advance_to(idx)
            line = self.lines[self.index].strip()
            self.index += 1
            key, value_token = self._split_key_value(line)
            if value_token == "|":
                result[key] = self._parse_block_scalar(indent)
                continue
            if value_token == "":
                next_info = self._peek()
                if next_info is None or next_info[0] <= indent:
                    result[key] = None
                else:
                    if next_info[1].startswith("- "):
                        result[key] = self._parse_list(next_info[0])
                    else:
                        result[key] = self._parse_mapping(next_info[0])
                continue
            if value_token.startswith("[") and value_token.endswith("]"):
                result[key] = self._parse_inline_list(value_token)
                continue
            result[key] = self._parse_scalar(value_token)
        return result

    def _parse_list(self, indent: int) -> List[Any]:
        items: List[Any] = []
        while True:
            peek = self._peek()
            if peek is None:
                break
            current_indent, stripped, idx = peek
            if current_indent < indent:
                break
            if current_indent > indent:
                raise ValueError("unexpected increased indent in sequence")
            if not stripped.startswith("- ") and stripped != "-":
                break
            self._advance_to(idx)
            line = stripped
            self.index += 1
            item_text = line[1:].strip()
            if item_text == "|":
                items.append(self._parse_block_scalar(indent))
                continue
            if item_text == "":
                next_info = self._peek()
                if next_info is None or next_info[0] <= indent:
                    items.append(None)
                else:
                    if next_info[1].startswith("- "):
                        items.append(self._parse_list(next_info[0]))
                    else:
                        items.append(self._parse_mapping(next_info[0]))
                continue
            if item_text.startswith("[") and item_text.endswith("]"):
                items.append(self._parse_inline_list(item_text))
                continue
            if ":" in item_text and not item_text.startswith(("'", '"')):
                key, value_token = self._split_key_value(item_text)
                mapping: dict[str, Any] = {}
                if value_token == "|":
                    mapping[key] = self._parse_block_scalar(indent)
                elif value_token == "":
                    next_info = self._peek()
                    if next_info is None or next_info[0] <= indent:
                        mapping[key] = None
                    else:
                        if next_info[1].startswith("- "):
                            mapping[key] = self._parse_list(next_info[0])
                        else:
                            mapping[key] = self._parse_mapping(next_info[0])
                elif value_token.startswith("[") and value_token.endswith("]"):
                    mapping[key] = self._parse_inline_list(value_token)
                else:
                    mapping[key] = self._parse_scalar(value_token)
                next_info = self._peek()
                if next_info and next_info[0] > indent and not next_info[1].startswith("- "):
                    extra = self._parse_mapping(next_info[0])
                    mapping.update(extra)
                items.append(mapping)
                continue
            items.append(self._parse_scalar(item_text))
        return items

    def _parse_inline_list(self, token: str) -> List[Any]:
        inner = token[1:-1].strip()
        if not inner:
            return []
        items: List[str] = []
        current: List[str] = []
        quote: Optional[str] = None
        escape = False
        for ch in inner:
            if quote:
                if escape:
                    current.append(ch)
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == quote:
                    quote = None
                else:
                    current.append(ch)
                continue
            if ch in ('"', "'"):
                quote = ch
                continue
            if ch == ",":
                items.append("".join(current).strip())
                current = []
                continue
            current.append(ch)
        items.append("".join(current).strip())
        return [self._parse_scalar(item) for item in items if item]

    def _parse_scalar(self, token: str) -> Any:
        lowered = token.lower()
        if lowered in {"null", "none", "~"}:
            return None
        if lowered == "true":
            return True
        if lowered == "false":
            return False
        if token.startswith("'") and token.endswith("'") and len(token) >= 2:
            return token[1:-1]
        if token.startswith('"') and token.endswith('"') and len(token) >= 2:
            return bytes(token[1:-1], "utf-8").decode("unicode_escape")
        try:
            if token.startswith("0") and token not in {"0", "0.0"} and not token.startswith("0."):
                raise ValueError
            if any(ch in token for ch in ".eE"):
                return float(token)
            return int(token)
        except ValueError:
            try:
                return float(token)
            except ValueError:
                return token

    def _parse_block_scalar(self, base_indent: int) -> str:
        lines: List[str] = []
        min_indent: Optional[int] = None
        while self.index < len(self.lines):
            raw = self.lines[self.index]
            stripped = raw.strip("\n")
            indent = len(raw) - len(raw.lstrip(" "))
            if not stripped:
                if min_indent is None:
                    self.index += 1
                    lines.append("")
                    continue
                if indent >= min_indent:
                    self.index += 1
                    lines.append(raw[min_indent:])
                    continue
                break
            if indent <= base_indent:
                break
            if min_indent is None:
                min_indent = indent
            if indent < min_indent:
                break
            lines.append(raw[min_indent:])
            self.index += 1
        while lines and lines[-1] == "":
            lines.pop()
        return "\n".join(lines)


def _ensure_text(stream: Union[str, bytes, Any]) -> str:
    if hasattr(stream, "read"):
        data = stream.read()
        if isinstance(data, bytes):
            return data.decode("utf-8")
        return str(data)
    if isinstance(stream, bytes):
        return stream.decode("utf-8")
    return str(stream)


def safe_load(stream: Union[str, bytes, Any]) -> Any:
    """Load YAML content using a very small subset parser."""
    text = _ensure_text(stream)
    parser = _SimpleYAMLParser(text)
    return parser.parse()


def load(stream: Union[str, bytes, Any], Loader: Any | None = None) -> Any:  # noqa: N802
    return safe_load(stream)


def safe_dump(data: Any, stream: Any | None = None, *, sort_keys: bool = True) -> str:
    """Serialise *data* as YAML (JSON compatible)."""
    text = json.dumps(data, indent=2, ensure_ascii=False, sort_keys=sort_keys)
    if stream is not None:
        stream.write(text)
        return text
    return text


def dump(data: Any, stream: Any | None = None, Dumper: Any | None = None, **kwargs: Any) -> str:  # noqa: N802
    sort_keys = kwargs.get("sort_keys", True)
    return safe_dump(data, stream=stream, sort_keys=sort_keys)
