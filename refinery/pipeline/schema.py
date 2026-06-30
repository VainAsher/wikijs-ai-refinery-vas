"""Pipeline / Pass config data structures and the YAML template loader.

Lightweight dataclasses (matching the project's dataclass convention) plus a loader
that validates a pipeline template up front and fails with a clear, field-named error
rather than blowing up mid-run.
"""
from __future__ import annotations
import dataclasses
from pathlib import Path
from typing import Any, Dict, List
import yaml


class PipelineConfigError(ValueError):
    """Raised when a pipeline template is structurally invalid."""


# Execution modes for a pass. llm_optional => use the model if configured, else a
# deterministic fallback; llm_required => needs a model; deterministic => never calls one.
KNOWN_MODES = {'deterministic', 'llm_optional', 'llm_required'}

# The set of pass IDs the pipeline knows how to run. A template referencing anything
# outside this set is rejected at load time (no silent no-op passes).
KNOWN_PASS_IDS = {
    'clean_markdown', 'classify', 'chunk', 'fact_find', 'draft',
    'voice_pass', 'brand_pass', 'audience_check', 'seo_enrichment',
    'technical_accuracy_check', 'technical_repair', 'embed_suggestions',
    'provenance_attach', 'final_polish', 'final_gate',
    'service_registry_extract', 'iac_reference_extract', 'support_macro_generation',
}


def normalise_gate(gate: Any) -> Dict[str, Any]:
    """Normalise a gate entry to {'name': str, 'value': Any?}. Templates write gates
    as either a bare string (``no_secret_leak``) or a single-key mapping
    (``brand_score_min: 80``)."""
    if isinstance(gate, str):
        return {'name': gate}
    if isinstance(gate, dict):
        if 'name' in gate:
            return {'name': str(gate['name']), **{k: v for k, v in gate.items() if k != 'name'}}
        if len(gate) == 1:
            (k, v), = gate.items()
            return {'name': str(k), 'value': v}
    raise PipelineConfigError(f'Invalid gate entry: {gate!r}')


@dataclasses.dataclass
class PassConfig:
    id: str
    name: str = ''
    stage: str = ''
    mode: str = 'deterministic'
    input_format: str = 'markdown'
    output_format: str = 'markdown'
    allowed_changes: List[str] = dataclasses.field(default_factory=list)
    forbidden_changes: List[str] = dataclasses.field(default_factory=list)
    progressive_context: Dict[str, Any] = dataclasses.field(default_factory=dict)
    retrieval: Dict[str, Any] = dataclasses.field(default_factory=dict)
    gates: List[Dict[str, Any]] = dataclasses.field(default_factory=list)
    dials: Dict[str, Any] = dataclasses.field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return dataclasses.asdict(self)


@dataclasses.dataclass
class PipelineConfig:
    id: str
    name: str = ''
    description: str = ''
    passes: List[PassConfig] = dataclasses.field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {'id': self.id, 'name': self.name, 'description': self.description,
                'passes': [p.to_dict() for p in self.passes]}


def _pass_from_dict(raw: Any, where: str) -> PassConfig:
    if not isinstance(raw, dict):
        raise PipelineConfigError(f'{where}: each pass must be a mapping, got {type(raw).__name__}')
    pid = str(raw.get('id') or '').strip()
    if not pid:
        raise PipelineConfigError(f'{where}: pass is missing an "id"')
    if pid not in KNOWN_PASS_IDS:
        raise PipelineConfigError(f'{where}: unknown pass id "{pid}" (known: {", ".join(sorted(KNOWN_PASS_IDS))})')
    mode = str(raw.get('mode') or 'deterministic')
    if mode not in KNOWN_MODES:
        raise PipelineConfigError(f'{where}: pass "{pid}" has invalid mode "{mode}" (known: {", ".join(sorted(KNOWN_MODES))})')
    return PassConfig(
        id=pid, name=str(raw.get('name') or pid), stage=str(raw.get('stage') or ''),
        mode=mode, input_format=str(raw.get('input_format') or 'markdown'),
        output_format=str(raw.get('output_format') or 'markdown'),
        allowed_changes=[str(x) for x in (raw.get('allowed_changes') or [])],
        forbidden_changes=[str(x) for x in (raw.get('forbidden_changes') or [])],
        progressive_context=dict(raw.get('progressive_context') or {}),
        retrieval=dict(raw.get('retrieval') or {}),
        gates=[normalise_gate(g) for g in (raw.get('gates') or [])],
        dials=dict(raw.get('dials') or {}),
    )


def load_pipeline_dict(data: Any) -> PipelineConfig:
    """Validate and build a PipelineConfig from a parsed mapping."""
    if not isinstance(data, dict):
        raise PipelineConfigError('Pipeline template must be a mapping at the top level')
    pid = str(data.get('id') or '').strip()
    if not pid:
        raise PipelineConfigError('Pipeline is missing an "id"')
    raw_passes = data.get('passes')
    if not isinstance(raw_passes, list) or not raw_passes:
        raise PipelineConfigError(f'Pipeline "{pid}" must define a non-empty "passes" list')
    passes = [_pass_from_dict(p, f'pipeline "{pid}" pass[{i}]') for i, p in enumerate(raw_passes)]
    return PipelineConfig(id=pid, name=str(data.get('name') or pid),
                          description=str(data.get('description') or ''), passes=passes)


def load_pipeline_file(path) -> PipelineConfig:
    p = Path(path)
    try:
        data = yaml.safe_load(p.read_text(encoding='utf-8'))
    except yaml.YAMLError as e:
        raise PipelineConfigError(f'{p.name}: invalid YAML — {e}') from e
    return load_pipeline_dict(data)


def load_pipeline_templates(directory) -> Dict[str, PipelineConfig]:
    """Load every *.yml/*.yaml template in a directory, keyed by pipeline id. A single
    bad template raises (so a broken template is caught, not silently skipped)."""
    out: Dict[str, PipelineConfig] = {}
    d = Path(directory)
    if not d.exists():
        return out
    for f in sorted([*d.glob('*.yml'), *d.glob('*.yaml')]):
        cfg = load_pipeline_file(f)
        out[cfg.id] = cfg
    return out
