"""Lexical boundaries shared by the rule-file and single-rule parsers."""

from dataclasses import dataclass
import re


@dataclass(frozen=True)
class Token:
    kind: str
    text: str
    start: int
    end: int
    line: int
    column: int


def tokenize(source):
    tokens = []
    i = 0
    line = column = 1
    while i < len(source):
        start, row, col = i, line, column
        char = source[i]
        if char in " \t\r":
            i += 1
            column += 1
            continue
        if char == "#" or source.startswith("//", i):
            while i < len(source) and source[i] != "\n":
                i += 1
                column += 1
            continue
        if char == "\n":
            i += 1
            line += 1
            column = 1
            tokens.append(Token("newline", "\n", start, i, row, col))
            continue
        regex_start = (char == "/" and len(tokens) >= 2 and tokens[-1].text == "="
                       and tokens[-2].text.startswith("$"))
        single_quote_start = char == "'" and tokens and tokens[-1].text == "="
        if char == '"' or single_quote_start or regex_start:
            quote = char
            kind = "regex" if quote == "/" else "string"
            i += 1
            escaped = False
            in_class = False
            while i < len(source):
                current = source[i]
                if current == "\n":
                    raise ValueError(f"Unclosed {kind} at line {row}, column {col}")
                if escaped:
                    escaped = False
                elif current == "\\":
                    escaped = True
                elif kind == "regex" and current == "[":
                    in_class = True
                elif kind == "regex" and current == "]":
                    in_class = False
                elif current == quote and not in_class:
                    i += 1
                    break
                i += 1
            else:
                raise ValueError(f"Unclosed {kind} at line {row}, column {col}")
        else:
            match = re.match(r"\$[A-Za-z0-9_]+|[A-Za-z_][A-Za-z0-9_]*|[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?", source[i:])
            if match:
                i += len(match[0])
                kind = "word"
            else:
                i += 1
                kind = char
        tokens.append(Token(kind, source[start:i], start, i, row, col))
        column += i - start
    return tokens


def rule_spans(source):
    tokens = [t for t in tokenize(source) if t.kind != "newline"]
    spans = []
    i = 0
    while i < len(tokens):
        first = tokens[i]
        if first.text != "rule" or i + 2 >= len(tokens) or tokens[i + 2].text != "{":
            raise ValueError(f"Expected rule declaration at line {first.line}, column {first.column}")
        if not re.fullmatch(r"\w+", tokens[i + 1].text):
            raise ValueError(f"Invalid rule name at line {first.line}")
        opening = i + 2
        stack = []
        section = None
        i = opening
        while i < len(tokens):
            token = tokens[i]
            if len(stack) == 1 and token.kind == "word" and i + 1 < len(tokens) and tokens[i + 1].text == ":":
                section = token.text
            if token.kind in ("{", "["):
                stack.append(token.kind)
            elif token.kind in ("}", "]"):
                if not stack or stack.pop() != {"}": "{", "]": "["}[token.kind]:
                    raise ValueError(f"{'Invalid keyword pattern: ' if section == 'keywords' else ''}Mismatched delimiter at line {token.line}, column {token.column}")
                if not stack:
                    spans.append((first.start, token.end))
                    i += 1
                    break
            i += 1
        else:
            raise ValueError(f"Unclosed rule at line {first.line}, column {first.column}")
    return spans


def sections(source):
    spans = rule_spans(source)
    if len(spans) != 1:
        raise ValueError("Expected exactly one rule")
    tokens = [t for t in tokenize(source) if t.kind != "newline"]
    name = tokens[1].text
    depth = 0
    headers = []
    for i, token in enumerate(tokens):
        if token.kind == "{":
            depth += 1
        elif token.kind == "}":
            depth -= 1
        elif (depth == 1 and token.kind == "word" and i + 1 < len(tokens)
              and tokens[i + 1].kind == ":"
              and (tokens[i - 1].line < token.line or tokens[i - 1].kind == "{")):
            headers.append((token.text.lower(), token.start, tokens[i + 1].end))
    if not headers or source[tokens[2].end:headers[0][1]].strip():
        # Comments are lexical whitespace; inspect tokens rather than raw text.
        if not headers or any(t.start >= tokens[2].end and t.start < headers[0][1] for t in tokens):
            raise ValueError(f"Rule '{name}' requires a section")
    result = {}
    for i, (header, start, body) in enumerate(headers):
        if header in result:
            raise ValueError(f"Duplicate section '{header}' in rule '{name}'")
        end = headers[i + 1][1] if i + 1 < len(headers) else tokens[-1].start
        result[header] = (source[body:end], source[:body].count("\n"))
    return name, result
