"""Pinned SDK compatibility checks. No model downloads or inference."""

from itertools import product
from types import SimpleNamespace

import pytest

from nova.evaluators.sys1.laya import preflight
from nova.evaluators.sys1.models import ModelError
from test_laya import Tokenizer


def test_preflight_matches_pinned_sequence_builder():
    common = pytest.importorskip("laya.common")
    tok = Tokenizer()
    for kind, length, count, head_limit, total_limit, state in product(
        ("noul", "choice", "score"), (1, 12, 45, 50), (2, 4, 10), (32, 64, 192), (64, 1024), ("", "日本語" * 10),
    ):
        criteria = (["x" * length] * count if kind == "score" else
                    {str(i): "x" * length for i in range(count)} if kind == "choice" else
                    {"true": "x" * length, "false": "y" * length})
        q = {"type": kind, "instructions": "Test?", "criteria": criteria}
        internal = {"t": kind, "ins": q["instructions"], "crit": criteria}
        # Construct the complete unsliced sequence independently, then compare
        # to the exact SDK sequence; equality means preflight must accept it.
        full = [tok.cls_token_id] + list(f"{kind} question: Test?") + [tok.sep_token_id]
        for option in common.render_options(internal):
            full += [tok.mask_token_id] + list(" " + option)
        full += [tok.sep_token_id] + list(state) + [tok.sep_token_id]
        actual, markers = common.build_sequence(tok, state, internal, total_limit, head_limit)
        agent = SimpleNamespace(tok=tok, cfg={"max_len": total_limit, "head_max_len": head_limit})
        if actual == full:
            assert preflight(agent, state, q) == len(full)
            assert len(markers) == len(common.render_options(internal))
        else:
            with pytest.raises(ModelError):
                preflight(agent, state, q)
