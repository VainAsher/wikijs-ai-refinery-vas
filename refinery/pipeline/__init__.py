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

__all__ = [
    'PassConfig', 'PipelineConfig', 'PipelineConfigError',
    'KNOWN_MODES', 'KNOWN_PASS_IDS',
    'load_pipeline_dict', 'load_pipeline_file', 'load_pipeline_templates',
    'PipelineState', 'PassReport',
]
