import pytest
from pathlib import Path
from refinery.pipeline import (
    PassConfig, PipelineConfig, PipelineConfigError,
    load_pipeline_dict, load_pipeline_templates,
)

REPO = Path(__file__).resolve().parent.parent


def test_seed_template_loads():
    templates = load_pipeline_templates(REPO / 'pipeline_templates')
    assert 'customer_guide_pipeline' in templates
    cfg = templates['customer_guide_pipeline']
    assert isinstance(cfg, PipelineConfig)
    ids = [p.id for p in cfg.passes]
    assert ids[0] == 'clean_markdown' and ids[-1] == 'final_gate'
    # gate normalisation: bare string and single-key mapping both become {'name': ...}
    brand = next(p for p in cfg.passes if p.id == 'brand_pass')
    assert {'name': 'brand_score_min', 'value': 80} in brand.gates
    clean = next(p for p in cfg.passes if p.id == 'clean_markdown')
    assert {'name': 'non_empty_output'} in clean.gates


def test_pass_config_defaults():
    cfg = load_pipeline_dict({'id': 'p', 'passes': [{'id': 'clean_markdown'}]})
    p = cfg.passes[0]
    assert isinstance(p, PassConfig)
    assert p.mode == 'deterministic' and p.input_format == 'markdown'
    assert p.name == 'clean_markdown' and p.allowed_changes == [] and p.gates == []


def test_unknown_pass_id_is_rejected():
    with pytest.raises(PipelineConfigError) as e:
        load_pipeline_dict({'id': 'p', 'passes': [{'id': 'make_coffee'}]})
    assert 'make_coffee' in str(e.value)


def test_invalid_templates_fail_clearly():
    with pytest.raises(PipelineConfigError):
        load_pipeline_dict({'name': 'no id'})                       # missing id
    with pytest.raises(PipelineConfigError):
        load_pipeline_dict({'id': 'p', 'passes': []})               # empty passes
    with pytest.raises(PipelineConfigError):
        load_pipeline_dict({'id': 'p', 'passes': [{'id': 'draft', 'mode': 'magic'}]})  # bad mode
