"""The endless generation loop: Smythe batches, style gates, and a steady release.

Each round builds a Smythe graph of design requests and runs it with Swarm:
local requests through the grid sampler, model requests through a text model
under the session's spending cap. Designs are compiled and judged; accepted
glyphs wait in a short queue and are released at a steady interval to the
archive, the feed and the web stream, so the rain receives a constant flow.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import time
from typing import Callable

from live import lanes
from live.compile import compile_spec
from live.style import StyleGate


@dataclass
class Settings:
    lanes: tuple[str, ...] = ("local",)
    model_provider: str = "anthropic"
    model: str | None = None
    max_usd: float = 1.0
    call_estimate_usd: float = 0.05
    batch: int = 8
    designs_per_model_call: int = 6
    concurrency: int = 4
    interval: float = 2.0
    backoff: float = 5.0          # pause after a model round that yields nothing
    seed: int = 0
    queue: int = 32
    limit: int | None = None


@dataclass
class Totals:
    accepted: int = 0
    rejected: int = 0
    spend_usd: float = 0.0
    by_lane: dict = field(default_factory=lambda: {"local": 0, "model": 0})
    model_stopped: str | None = None


class Runner:
    def __init__(self, settings: Settings, sinks: list, *, gate: StyleGate | None = None,
                 providers: dict | None = None, log: Callable[[str], None] = print):
        self.settings, self.sinks, self.log = settings, sinks, log
        self.gate = gate or StyleGate()
        self.providers = providers or {}
        self.totals = Totals()
        self.queue: list[dict] = []
        self.next_seed = settings.seed
        self.seq = 0
        self.examples: list[dict] = []
        self.session_prefix = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        self.stopped = False

    # ---------- Smythe batches ----------
    def _swarm(self, lane: str):
        from smythe import Swarm, Synthesizer, SynthesisStrategy

        if lane == "local":
            provider = self.providers.get("local") or lanes.local_provider()
            return Swarm(provider=provider, model=lanes.LOCAL_MODEL, parallel=True,
                         max_concurrency=self.settings.concurrency, max_budget_usd=0.0, artifact_dir=None,
                         synthesizer=Synthesizer(SynthesisStrategy.CONCATENATE))
        provider = self.providers.get("model") or lanes.model_provider(self.settings.model_provider)
        model = self.settings.model or lanes.MODEL_PROVIDERS[self.settings.model_provider][1]
        remaining = max(0.0, self.settings.max_usd - self.totals.spend_usd)
        return Swarm(provider=provider, model=model, parallel=True, max_concurrency=self.settings.concurrency,
                     max_budget_usd=remaining, artifact_dir=None,
                     synthesizer=Synthesizer(SynthesisStrategy.CONCATENATE))

    def _graph(self, lane: str):
        from smythe.graph import ExecutionGraph, FailurePolicy, Node, Topology

        nodes = []
        if lane == "local":
            per_node = max(1, self.settings.batch // max(1, self.settings.concurrency))
            for index in range(max(1, self.settings.concurrency)):
                nodes.append(Node(id=f"local-{self.next_seed}", label=lanes.request("local", seed=self.next_seed, count=per_node),
                                  failure_policy=FailurePolicy.SKIP, max_retries=0, metadata={"estimated_cost_usd": 0.0}))
                self.next_seed += per_node
        else:
            nodes.append(Node(id=f"model-{self.seq}-{int(time.time())}",
                              label=lanes.model_prompt(self.settings.designs_per_model_call, self.examples),
                              failure_policy=FailurePolicy.SKIP, max_retries=0,
                              metadata={"estimated_cost_usd": self.settings.call_estimate_usd}))
        return ExecutionGraph(topology=[Topology.BROADCAST_REDUCE], nodes=nodes)

    async def _batch(self, lane: str) -> None:
        from smythe.graph import NodeStatus

        graph = self._graph(lane)
        try:
            result = await self._swarm(lane).execute_async(graph)
            cost = float(result.total_cost_usd or 0.0)
        except Exception as error:  # a failed batch never stops the flow
            self.log(f"{lane} batch failed: {type(error).__name__}: {error}")
            cost = 0.0
        self.totals.spend_usd += cost
        for node in graph.nodes:
            if node.status is not NodeStatus.COMPLETED or node.result is None:
                continue
            text = str(node.result)
            if lane == "local":
                designs = [(item["spec"], item["seed"]) for item in json.loads(text)["designs"]]
            else:
                specs, problems = lanes.parse_designs(text)
                self.totals.rejected += len(problems)
                designs = [(spec, None) for spec in specs]
            for spec, seed in designs:
                self._judge(spec, seed, lane)

    def _judge(self, spec: dict, seed: int | None, lane: str) -> None:
        try:
            glyph = compile_spec(spec, seed=seed)
        except (ValueError, TypeError):
            self.totals.rejected += 1
            return
        report = self.gate.check(glyph)
        if not report.ok:
            self.totals.rejected += 1
            return
        self.seq += 1
        glyph_id = f"{self.session_prefix}-{self.seq:06d}"
        self.gate.remember(glyph_id, report)
        self.examples = ([glyph.spec] + self.examples)[:6]
        provider = None if lane == "local" else self.settings.model_provider
        model = lanes.LOCAL_MODEL if lane == "local" else (self.settings.model or lanes.MODEL_PROVIDERS[self.settings.model_provider][1])
        self.queue.append({
            "id": glyph_id, "seq": self.seq, "lane": lane, "seed": seed, "provider": provider, "model": model,
            "spec": glyph.spec, "sha256": glyph.sha256, "svg": glyph.svg, "polygons": glyph.polygons,
            "metrics": report.metrics, "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        })

    def _release(self) -> dict | None:
        if not self.queue:
            return None
        record = self.queue.pop(0)
        for sink in self.sinks:
            sink.write(record)
        self.totals.accepted += 1
        self.totals.by_lane[record["lane"]] += 1
        self.log(f"{record['id']}  {record['lane']:<5}  accepted {self.totals.accepted}  "
                 f"rejected {self.totals.rejected}  spend ${self.totals.spend_usd:.4f}")
        return record

    def _model_open(self) -> bool:
        if "model" not in self.settings.lanes or self.totals.model_stopped:
            return False
        if self.totals.spend_usd + self.settings.call_estimate_usd > self.settings.max_usd:
            self.totals.model_stopped = f"spending cap ${self.settings.max_usd:.2f} reached"
            self.log(f"model lane stopped: {self.totals.model_stopped}; " +
                     ("the local lane continues" if "local" in self.settings.lanes else "no lane remains"))
            return False
        return True

    async def run(self) -> Totals:
        """Generate and release glyphs until stopped, the limit is reached, or no lane remains."""
        rounds = 0
        while not self.stopped:
            if self.settings.limit is not None and self.totals.accepted >= self.settings.limit:
                break
            if len(self.queue) < self.settings.queue:
                model_turn = self._model_open() and (rounds % 2 == 1 or "local" not in self.settings.lanes)
                if model_turn:
                    before = self.seq
                    await self._batch("model")
                    if self.seq == before and not self.queue:
                        await asyncio.sleep(max(self.settings.interval, self.settings.backoff))
                elif "local" in self.settings.lanes:
                    await self._batch("local")
                elif not self.queue:
                    break
                rounds += 1
            released = self._release()
            if released is not None and self.settings.interval > 0:
                await asyncio.sleep(self.settings.interval)
        while self.queue and (self.settings.limit is None or self.totals.accepted < self.settings.limit) and not self.stopped:
            self._release()
        return self.totals
