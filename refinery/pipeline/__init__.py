"""Multi-pass enrichment pipeline (v2).

A Pipeline is an ordered sequence of bounded Passes that move a source document
through clean → classify → chunk → fact-find → draft → enrich → gate → review.
Governance stays deterministic: AI may suggest/draft/critique, but deterministic
code decides source governance, customer safety, publish eligibility, and gates.
"""
from refinery.pipeline.schema import (
    PassConfig, PipelineConfig, PipelineConfigError,
    KNOWN_MODES, KNOWN_PASS_IDS,
    load_pipeline_dict, load_pipeline_file, load_pipeline_templates,
)
from refinery.pipeline.state import PipelineState, PassReport
from refinery.pipeline.context import ContextBuilder, SAFETY_DENY
from refinery.pipeline.passes import PassDeps, EXECUTORS, run_pass
from refinery.pipeline.validators import evaluate_gates, VALIDATORS, CRITICAL_GATES
from refinery.pipeline.runner import run_pipeline, PipelineResult
from refinery.pipeline.service import run_and_persist, load_source_doc

__all__ = [
    'PassConfig', 'PipelineConfig', 'PipelineConfigError',
    'KNOWN_MODES', 'KNOWN_PASS_IDS',
    'load_pipeline_dict', 'load_pipeline_file', 'load_pipeline_templates',
    'PipelineState', 'PassReport',
    'ContextBuilder', 'SAFETY_DENY',
    'PassDeps', 'EXECUTORS', 'run_pass',
    'evaluate_gates', 'VALIDATORS', 'CRITICAL_GATES',
    'run_pipeline', 'PipelineResult',
    'run_and_persist', 'load_source_doc',
]
