"""Strict reader for Decision's deliberately small declaration grammar."""

import json
import re

from nova.core.structure import tokenize
from nova.core.decision import NoulPattern, ChoicePattern, ScorePattern


class Reader:
    def __init__(self, source, rule, offset):
        self.source = source
        self.quoted = {}
        self.tokens = tokenize(source)
        self.index = 0
        self.rule, self.offset, self.variable = rule, offset, "llm"

    def fail(self, message):
        token = self.tokens[min(self.index, len(self.tokens) - 1)] if self.tokens else None
        position = f"line {token.line + self.offset}, column {token.column}" if token else "end of section"
        raise ValueError(f"Rule '{self.rule}', {self.variable}, {position}: {message}")

    def peek(self):
        return self.tokens[self.index].text if self.index < len(self.tokens) else None

    def take(self, expected=None):
        token = self.peek()
        if token is None or (expected is not None and token != expected):
            self.fail(f"Expected {expected or 'value'}, found {token!r}")
        self.index += 1
        return token

    def newlines(self):
        while self.peek() == "\n":
            self.take()

    def string(self):
        value = self.take()
        if not value.startswith('"'):
            self.fail("Expected a double-quoted string")
        try:
            return json.loads(value)
        except ValueError:
            self.fail("Invalid string escape")

    def value(self):
        if self.peek() == "{":
            self.take()
            result = {}
            self.newlines()
            while self.peek() != "}":
                key = self.take()
                if not re.fullmatch(r"[A-Za-z0-9_]+", key):
                    self.fail("Invalid option identifier")
                if key in result:
                    self.fail(f"Duplicate option '{key}'")
                self.take("=")
                result[key] = self.string()
                if self.peek() not in ("\n", "}"):
                    self.fail("Expected newline after option")
                self.newlines()
            self.take("}")
            return result
        if self.peek() == "[":
            self.take()
            result = []
            self.newlines()
            while self.peek() != "]":
                result.append(self.string())
                self.newlines()
                if self.peek() != "]":
                    self.take(",")
                    self.newlines()
            self.take("]")
            return result
        if (self.peek() or "").startswith('"'):
            return self.string()
        try:
            return float(self.take())
        except ValueError:
            self.fail("Expected number, string, list or options block")

    def read(self, parse_quoted=None):
        patterns = {}
        self.newlines()
        contracts = {
            "noul": ({"true", "false", "threshold"}, set()),
            "choice": ({"options", "match"}, {"min_confidence"}),
            "score": ({"levels", "threshold"}, {"min_confidence"}),
        }
        while self.peek() is not None:
            start = self.tokens[self.index].start
            name = self.take()
            self.variable = name
            if not re.fullmatch(r"\$[A-Za-z0-9_]+", name) or name in patterns or name in self.quoted:
                self.fail("Invalid or duplicate variable")
            self.take("=")
            if parse_quoted is not None and (self.peek() or "").startswith('"'):
                while self.peek() not in (None, "\n"):
                    self.take()
                end = self.tokens[self.index].start if self.peek() is not None else len(self.source)
                self.quoted.update(parse_quoted([self.source[start:end]]))
                self.newlines()
                continue
            kind = self.take()
            if kind not in contracts:
                self.fail(f"Unknown decision model question type '{kind}'")
            question = self.string()
            self.take("{")
            self.newlines()
            fields = {}
            required, optional = contracts[kind]
            while self.peek() != "}":
                field = self.take()
                if field not in required | optional or field in fields:
                    self.fail(f"Unknown or duplicate setting '{field}'")
                self.take("=")
                fields[field] = self.value()
                if self.peek() not in ("\n", "}"):
                    self.fail("Expected newline after setting")
                self.newlines()
            self.take("}")
            if required - fields.keys():
                self.fail("Missing settings: " + ", ".join(sorted(required - fields.keys())))
            try:
                if kind == "noul":
                    pattern = NoulPattern(question, fields["true"], fields["false"], fields["threshold"])
                elif kind == "choice":
                    pattern = ChoicePattern(question, fields["options"], fields["match"], fields.get("min_confidence"))
                else:
                    pattern = ScorePattern(question, fields["levels"], fields["threshold"], fields.get("min_confidence"))
            except (TypeError, ValueError) as error:
                self.fail(str(error))
            patterns[name] = pattern
            if self.peek() not in (None, "\n"):
                self.fail("Expected newline after declaration")
            self.newlines()
        if not patterns and not self.quoted:
            self.fail("Empty llm section")
        return patterns


def parse_decision(source, rule, offset=0):
    return Reader(source, rule, offset).read()


def parse_llm(source, rule, offset, parse_quoted):
    reader = Reader(source, rule, offset)
    typed = reader.read(parse_quoted)
    return reader.quoted, typed


def has_typed_llm(source):
    tokens = tokenize(source)
    return any(tokens[i].text.startswith("$") and tokens[i + 1].text == "="
               and tokens[i + 2].text in ("noul", "choice", "score")
               for i in range(len(tokens) - 2))
