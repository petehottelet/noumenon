"""The two design lanes Smythe runs: local sampling and a live model.

Each Smythe node carries a design request. The local lane's provider answers it
by sampling the grid grammar, offline and at no cost. The model lane sends the
same request, with the grammar and style rules, to a text model through one of
Smythe's providers, and the model answers with specs in the same JSON form.
Either way, specs are compiled and judged by the same style gates.
"""

from __future__ import annotations

import json
import os
import re

from live.grammar import LAYOUTS, check_spec, sample_spec

MARKER = "NOUMENON_DESIGN_REQUEST:"
LOCAL_MODEL = "noumenon-grid-sampler"
MODEL_PROVIDERS = {
    # name: (Smythe provider class, default model, API key variable)
    "anthropic": ("AnthropicMessagesProvider", "claude-fable-5-1", "ANTHROPIC_API_KEY"),
    "openai": ("OpenAIResponsesProvider", "gpt-5.6-sol", "OPENAI_API_KEY"),
}

STYLE_BRIEF = """\
You design glyphs for Noumenon, a code-rain screensaver. Every glyph is abstract:
it must not read as a letter, numeral, arrow, pictogram or common symbol, even
mirrored or rotated. The style is blocky and stencil-like: straight bars and
stems of even thickness, straight-cut stroke ends, occasional rounded shoulders
where a stroke turns, and occasional leaning stems. Favor long strokes and
purposeful gaps over scattered single marks.

Write each glyph as JSON on a coarse grid. A glyph has a layout, "columns"
(two halves side by side) or "tiers" (two halves stacked), and two halves.
Each half is 5 rows along the strokes' long axis (top to bottom for columns,
left to right for tiers), each row 2 characters across the half: "#" filled,
"." empty. Rules:
- each half fills at least 2 cells; the glyph fills 7 to 12 cells in total;
- filled cells may not touch only at a corner;
- "round" may list "row,column,corner" (corner tl, tr, br or bl) only for the
  outer corner of a cell where a stroke turns: both sides at that corner open,
  both opposite sides filled, and the cell inside the turn empty;
- "lean" may be "left" or "right" only for a half holding one straight stem of
  3 or more cells, leaning into its empty column; otherwise null.

Example:
{"layout": "columns", "halves": [
  {"cells": ["##", "#.", "#.", "#.", "##"], "round": ["0,0,tl", "4,0,bl"], "lean": null},
  {"cells": ["..", "#.", "#.", "#.", ".."], "round": [], "lean": "right"}]}
"""


def request(lane: str, **fields) -> str:
    return MARKER + json.dumps({"lane": lane, **fields}, sort_keys=True)


def parse_request(prompt: str) -> dict:
    match = re.search(re.escape(MARKER) + r"(\{[^\r\n]+\})", prompt)
    if match is None:
        raise ValueError("only Noumenon design requests are accepted")
    return json.loads(match.group(1))


def model_prompt(count: int, examples: list[dict]) -> str:
    """The node label for a model-lane request: the brief, examples and the ask."""
    shown = "\n".join(json.dumps(spec, separators=(",", ":")) for spec in examples[:6])
    return (f"{STYLE_BRIEF}\nRecent accepted designs, for reference; do not copy them:\n{shown}\n\n"
            f"Design {count} new glyphs that differ from each other and from the references. "
            'Reply with only JSON: {"designs": [ ...specs... ]}\n'
            f"{request('model', count=count)}")


def parse_designs(text: str) -> tuple[list[dict], list[str]]:
    """Specs from a reply, and the reasons any were unusable."""
    body = text.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", body, re.S)
    if fenced:
        body = fenced.group(1)
    start, end = body.find("{"), body.rfind("}")
    if start < 0 or end < start:
        return [], ["the reply held no JSON object"]
    try:
        data = json.loads(body[start:end + 1])
    except json.JSONDecodeError as error:
        return [], [f"the reply was not valid JSON: {error.msg}"]
    designs = data.get("designs") if isinstance(data, dict) else None
    if not isinstance(designs, list):
        return [], ['the reply had no "designs" list']
    specs, problems = [], []
    for item in designs:
        try:
            specs.append(check_spec(item))
        except (ValueError, TypeError, AttributeError) as error:
            problems.append(str(error))
    return specs, problems


def model_provider(name: str):
    """Instantiate a Smythe text provider for the model lane."""
    import smythe

    if name not in MODEL_PROVIDERS:
        raise ValueError(f"model provider must be one of {sorted(MODEL_PROVIDERS)}")
    class_name, _, key = MODEL_PROVIDERS[name]
    if not os.environ.get(key):
        raise RuntimeError(f"the {name} model lane needs {key} in the environment")
    return getattr(smythe, class_name)()


def local_provider():
    """A Smythe provider that answers design requests by sampling the grid grammar."""
    from smythe import CompletionResult, Provider

    class LocalDesignProvider(Provider):
        def budget_estimate_usd(self, model):
            return 0.0

        async def complete(self, system, prompt, model):
            ask = parse_request(prompt)
            if ask.get("lane") != "local":
                raise ValueError("the local provider answers local design requests only")
            designs = [{"seed": seed, "spec": sample_spec(seed)} for seed in range(ask["seed"], ask["seed"] + ask["count"])]
            return CompletionResult(text=json.dumps({"designs": designs}), cost_usd=0.0,
                                    prompt_tokens=0, completion_tokens=0)

    return LocalDesignProvider()


__all__ = ["LAYOUTS", "MARKER", "MODEL_PROVIDERS", "LOCAL_MODEL", "STYLE_BRIEF", "request", "parse_request",
           "model_prompt", "parse_designs", "model_provider", "local_provider"]
