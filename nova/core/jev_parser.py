"""Strict reader for Jev's deliberately small declaration grammar."""

import json
import re

from nova.core.structure import tokenize
from nova.core.jev import NoulPattern, ChoicePattern, ScorePattern


class Reader:
    def __init__(self, source, rule, offset):
        self.tokens = tokenize(source)
        self.index = 0
        self.rule, self.offset, self.variable = rule, offset, "jev"

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

    def read(self):
        patterns = {}
        self.newlines()
        contracts = {
            "noul": ({"true", "false", "threshold"}, set()),
            "choice": ({"options", "match"}, {"min_confidence"}),
            "score": ({"levels", "threshold"}, {"min_confidence"}),
        }
        while self.peek() is not None:
            name = self.take()
            self.variable = name
            if not re.fullmatch(r"\$[A-Za-z0-9_]+", name) or name in patterns:
                self.fail("Invalid or duplicate variable")
            self.take("=")
            kind = self.take()
            if kind not in contracts:
                self.fail(f"Unknown Jev primitive '{kind}'")
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
        if not patterns:
            self.fail("Empty Jev section")
        return patterns


def parse_jev(source, rule, offset=0):
    return Reader(source, rule, offset).read()
