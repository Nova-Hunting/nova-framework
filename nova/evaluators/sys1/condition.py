"""Restricted Boolean grammar with declaration-aware, three-state evaluation."""

from dataclasses import dataclass
import re
from nova.core.sys1 import Predicate

T, F, U = Predicate.TRUE, Predicate.FALSE, Predicate.UNKNOWN


@dataclass(frozen=True)
class Node:
    operation: str
    children: tuple = ()
    references: tuple = ()
    count: int = 1

    def evaluate(self, values):
        if self.operation == "count":
            states = [values.get(ref, U) for ref in self.references]
            yes = states.count(T)
            unknown = states.count(U)
            return T if yes >= self.count else F if yes + unknown < self.count else U
        states = [child.evaluate(values) for child in self.children]
        if self.operation == "not":
            return {T: F, F: T, U: U}[states[0]]
        if self.operation == "and":
            return F if F in states else U if U in states else T
        return T if T in states else U if U in states else F

    def needed(self, values):
        if self.evaluate(values) is not U:
            return set()
        if self.operation == "count":
            return {ref for ref in self.references if values.get(ref, U) is U}
        return set().union(*(child.needed(values) for child in self.children))


def declarations(rule):
    return {"keywords": rule.keywords, "semantics": rule.semantics, "llm": rule.llms, "sys1": rule.sys1}


class Compiler:
    token = re.compile(r"(?:keywords|semantics|llm|sys1)\.(?:\$[A-Za-z0-9_]+\*?|\*)|\$[A-Za-z0-9_]+\*?|[A-Za-z_][A-Za-z0-9_]*|\d+|[()]")

    def __init__(self, condition, sections):
        self.tokens = []
        pos = 0
        for match in self.token.finditer(condition):
            if condition[pos:match.start()].strip():
                raise ValueError("Invalid condition syntax")
            self.tokens.append(match[0])
            pos = match.end()
        if condition[pos:].strip():
            raise ValueError("Invalid condition syntax")
        self.index, self.sections = 0, sections

    def peek(self):
        return self.tokens[self.index] if self.index < len(self.tokens) else None

    def take(self, expected=None):
        token = self.peek()
        if token is None or (expected is not None and token != expected):
            raise ValueError(f"Expected {expected or 'predicate'}, found {token!r}")
        self.index += 1
        return token

    def refs(self, selector):
        if selector in self.sections:
            return tuple(f"{selector}.{key}" for key in self.sections[selector])
        if "." in selector:
            section, name = selector.split(".", 1)
            if section not in self.sections:
                raise ValueError(f"Unknown section '{section}'")
            candidates = [f"{section}.{key}" for key in self.sections[section]
                          if (key.startswith(name[:-1]) if name.endswith("*") else key == name)]
        else:
            candidates = [f"{section}.{key}" for section, entries in self.sections.items() for key in entries
                          if (key.startswith(selector[:-1]) if selector.endswith("*") else key == selector)]
            if not selector.endswith("*") and len(candidates) > 1:
                raise ValueError(f"Ambiguous reference '{selector}'; qualify its section")
        if not candidates:
            raise ValueError(f"Undeclared reference '{selector}'")
        return tuple(candidates)

    def expression(self, level=0):
        if level < 2:
            operation = ("or", "and")[level]
            children = [self.expression(level + 1)]
            while self.peek() == operation:
                self.take()
                children.append(self.expression(level + 1))
            return children[0] if len(children) == 1 else Node(operation, tuple(children))
        if self.peek() == "not":
            self.take()
            return Node("not", (self.expression(2),))
        if self.peek() == "(":
            self.take()
            node = self.expression()
            self.take(")")
            return node
        token = self.take()
        if token in ("any", "all") or token.isdigit():
            self.take("of")
            wrapped = self.peek() == "("
            if wrapped:
                self.take()
            selector = self.take()
            refs = self.refs(selector)
            if wrapped:
                self.take(")")
            count = len(refs) if token == "all" else 1 if token == "any" else int(token)
            if not refs or count < 1 or count > len(refs):
                raise ValueError("Quantifier count must be within declared variables")
            return Node("count", references=refs, count=count)
        if token in self.sections or (token.startswith("$") and token.endswith("*")):
            raise ValueError("Use a qualified wildcard or a quantifier")
        return Node("count", references=self.refs(token))


def compile_condition(rule):
    compiler = Compiler(rule.condition, declarations(rule))
    node = compiler.expression()
    if compiler.peek() is not None:
        raise ValueError(f"Unexpected condition token '{compiler.peek()}'")
    return node
