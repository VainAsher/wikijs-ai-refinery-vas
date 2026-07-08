from refinery.core import (
    SourceDoc, Classification, TRAINING_ARTIFACT_TARGETS,
    validate_training_artifact, transform_to_training_artifact,
)


def test_training_targets_registered_in_taxonomy(taxonomy):
    for t in TRAINING_ARTIFACT_TARGETS:
        assert f'rewrite_into_{t}' in taxonomy['adaptation_actions']
        assert t in taxonomy['doc_types']


def test_validate_training_artifact_accepts_well_shaped_mission():
    data = {'id': 'ssh-key', 'title': 'SSH Key', 'topic': 'ssh', 'difficulty': 2, 'estimated_minutes': 5,
            'briefing': 'Fix the thing.', 'quizzes': [{'id': 'q1', 'prompt': 'p', 'choices': ['a', 'b'], 'correctAnswers': [1]}]}
    ok, reason = validate_training_artifact('bisectbot_mission', data)
    assert ok, reason


def test_validate_training_artifact_rejects_out_of_range_correct_answer():
    # Shape-valid (right keys, right types) but the index doesn't point at a real choice -
    # the exact failure mode seen from real Ollama output that would otherwise silently
    # break a downstream consumer's own stricter validator.
    data = {'id': 'x', 'title': 'X', 'briefing': 'b',
            'quizzes': [{'id': 'q1', 'prompt': 'p', 'choices': ['a', 'b', 'c'], 'correctAnswers': [3]}]}
    ok, reason = validate_training_artifact('bisectbot_mission', data)
    assert not ok
    assert 'out-of-range' in reason


def test_validate_training_artifact_rejects_missing_fields():
    ok, reason = validate_training_artifact('ticketlab_scenario', {'id': 'x', 'title': 'X'})
    assert not ok
    assert 'ticket_subject' in reason


def test_validate_training_artifact_rejects_unknown_type():
    ok, reason = validate_training_artifact('not_a_real_type', {'id': 'x', 'title': 'X'})
    assert not ok


def test_transform_to_training_artifact_fallback_without_model():
    doc = SourceDoc(title='Ark Cluster Troubleshooting', content='cluster sync tips', source='mediawiki', source_id='1')
    c = Classification(title='Ark Cluster Troubleshooting', description='', source='mediawiki')
    out = transform_to_training_artifact(doc, c, 'bisectbot_mission', model=None)
    assert out.source == 'vainasherstudios_transform'
    assert out.raw_metadata['artifact_type'] == 'bisectbot_mission'
    import json
    data = json.loads(out.content)
    ok, reason = validate_training_artifact('bisectbot_mission', data)
    assert ok, reason
    assert 'NEEDS AUTHOR REVIEW' in data['briefing']  # deterministic fallback path, not a real AI draft


def test_transform_to_training_artifact_quiz_fallback():
    doc = SourceDoc(title='V Rising RCON', content='rcon commands', source='zendesk', source_id='2')
    c = Classification(title='V Rising RCON', description='', source='zendesk')
    out = transform_to_training_artifact(doc, c, 'quiz', model=None)
    import json
    data = json.loads(out.content)
    ok, reason = validate_training_artifact('quiz', data)
    assert ok, reason
