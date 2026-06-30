"""PipelineState (progressive context accumulator) and PassReport (per-pass audit).

Both are plain dataclasses that round-trip to/from JSON so a run can be persisted and
inspected afterwards. Earlier passes write structured outputs (facts, draft, seo
metadata, ...) that later passes read via the ContextBuilder.
"""
from __future__ import annotations
import dataclasses
from typing import Any, Dict, List


@dataclasses.dataclass
class PassReport:
    pass_id: str
    status: str = 'ok'                 # ok | skipped | failed | gate_failed
    mode: str = 'deterministic'        # deterministic | llm | fallback
    model: str = ''
    warnings: List[str] = dataclasses.field(default_factory=list)
    errors: List[str] = dataclasses.field(default_factory=list)
    changed: bool = False
    latency_ms: int = 0
    metadata: Dict[str, Any] = dataclasses.field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> 'PassReport':
        allowed = {f.name for f in dataclasses.fields(cls)}
        return cls(**{k: v for k, v in (d or {}).items() if k in allowed})


@dataclasses.dataclass
class PipelineState:
    source_doc_ids: List[int] = dataclasses.field(default_factory=list)
    target_action: str = 'rewrite_into_customer_guide'
    service: str = 'unknown'
    audience: str = 'unknown'
    current_markdown: str = ''
    classification: Dict[str, Any] = dataclasses.field(default_factory=dict)
    approved_facts: List[str] = dataclasses.field(default_factory=list)
    assumptions: List[str] = dataclasses.field(default_factory=list)
    risks: List[str] = dataclasses.field(default_factory=list)
    warnings: List[str] = dataclasses.field(default_factory=list)
    seo_metadata: Dict[str, Any] = dataclasses.field(default_factory=dict)
    embed_suggestions: List[Dict[str, Any]] = dataclasses.field(default_factory=list)
    provenance: List[Dict[str, Any]] = dataclasses.field(default_factory=list)
    pass_reports: List[Dict[str, Any]] = dataclasses.field(default_factory=list)

    def add_report(self, report: PassReport) -> None:
        self.pass_reports.append(report.to_dict())

    def to_dict(self) -> Dict[str, Any]:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> 'PipelineState':
        allowed = {f.name for f in dataclasses.fields(cls)}
        return cls(**{k: v for k, v in (d or {}).items() if k in allowed})
