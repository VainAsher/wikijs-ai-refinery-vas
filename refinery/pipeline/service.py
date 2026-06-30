"""Run-and-persist glue shared by the UI and CLI.

Loads a source doc from the Store, runs the pipeline, and persists everything the
schema expects: the pipeline_run, each pass_run, the generated draft doc (+ its chunks),
and the source->draft lineage. Returns ids/status for the caller to surface. The draft
is created with needs_review governance — never auto-published.
"""
from __future__ import annotations
import json
from typing import Any, Dict, Optional

from refinery.core import SourceDoc, build_wiki_path
from refinery.chunking import chunk_markdown
from refinery.pipeline.context import ContextBuilder
from refinery.pipeline.passes import PassDeps
from refinery.pipeline.runner import run_pipeline
from refinery.pipeline.schema import PipelineConfig


def load_source_doc(store, doc_id: int) -> SourceDoc:
    row = store.get_doc(doc_id)
    return SourceDoc(title=row['title'], content=row['content'], source=row['source'],
                     source_id=row['source_id'] or '', source_url=row['source_url'] or '',
                     original_updated_at=row['original_updated_at'] or '',
                     raw_metadata=json.loads(row['raw_metadata_json'] or '{}'))


def run_and_persist(store, config: PipelineConfig, *, source_doc_id: int, taxonomy: Dict[str, Any],
                    brand: Optional[Dict[str, Any]] = None, model: Optional[str] = None,
                    ollama_url: str = 'http://localhost:11434/api/generate',
                    target_action: str = 'rewrite_into_customer_guide',
                    service: str = 'unknown', audience: str = 'unknown',
                    collections: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    source = load_source_doc(store, source_doc_id)
    deps = PassDeps(taxonomy=taxonomy, brand=brand or {}, model=model, ollama_url=ollama_url,
                    context_builder=ContextBuilder(collections=collections or {}),
                    source_content=source.content, source_doc=source)
    run_id = store.add_pipeline_run(pipeline_id=config.id, source_doc_ids=[source_doc_id],
                                    target_action=target_action, service=service, audience=audience)
    result = run_pipeline(config, deps, target_action=target_action, service=service,
                          audience=audience, source_doc_ids=[source_doc_id])
    for rep in result.state.pass_reports:
        store.add_pass_run(run_id, rep)
    new_doc_id = store.add_doc(result.draft, result.classification, build_wiki_path(result.classification))
    store.replace_doc_chunks(new_doc_id, chunk_markdown(result.draft.content, doc_id=new_doc_id))
    store.add_doc_lineage(parent_doc_id=source_doc_id, child_doc_id=new_doc_id,
                          relationship='pipeline_draft', pipeline_run_id=run_id, pass_id='')
    store.finish_pipeline_run(run_id, status=result.status, state=result.state.to_dict(), new_doc_id=new_doc_id)
    return {'run_id': run_id, 'new_doc_id': new_doc_id, 'status': result.status,
            'gate_failures': result.gate_failures, 'pass_count': len(result.state.pass_reports)}
