from refinery.core import (
    SourceDoc, Classification, TRAINING_ARTIFACT_TARGETS,
    validate_training_artifact, transform_to_training_artifact,
)


def test_training_targets_registered_in_taxonomy(taxonomy):
    for t in TRAINING_ARTIFACT_TARGETS:
        assert f'rewrite_into_{t}' in taxonomy['adaptation_actions']
        assert t in taxonomy['doc_types']


def test_validate_accepts_well_shaped_mission_pack():
    # The exact TrainingMissionPack shape BisectBot's validatePack() consumes.
    data = {
        'schemaVersion': 1, 'contentType': 'bisectbot.trainingMission',
        'mission': {'id': 'ssh-key', 'title': 'SSH Key', 'customerReport': 'Customer cannot connect over SSH.'},
        'quizzes': [{'id': 'q1', 'type': 'multiple_choice', 'title': 't', 'question': 'Which command?',
                     'choices': ['a', 'b'], 'correctAnswers': [1], 'explanation': 'because'}],
    }
    assert validate_training_artifact('bisectbot_mission', data)


def test_validate_rejects_out_of_range_correct_answer():
    # Shape-valid but the index points past the choices list - the exact
    # failure mode seen from real Ollama output; BisectBot's own validator
    # rejects it, so it must never survive here.
    data = {
        'mission': {'id': 'x', 'title': 'X'},
        'quizzes': [{'question': 'q?', 'choices': ['a', 'b', 'c'], 'correctAnswers': [3]}],
    }
    assert not validate_training_artifact('bisectbot_mission', data)


def test_validate_rejects_flat_non_pack_shape():
    # Regression for the 2026-07-08 port bug: a flat {id,title,briefing,quizzes}
    # object is NOT a TrainingMissionPack and must not pass.
    data = {'id': 'x', 'title': 'X', 'briefing': 'b',
            'quizzes': [{'question': 'q?', 'choices': ['a', 'b'], 'correctAnswers': [0]}]}
    assert not validate_training_artifact('bisectbot_mission', data)


def test_validate_scenario_requires_fault_and_solutions():
    assert not validate_training_artifact('ticketlab_scenario', {'metadata': {'id': 'x'}, 'ticket': {'subject': 's'}})


def test_validate_unknown_type_is_false():
    assert not validate_training_artifact('not_a_real_type', {'anything': 1})


def test_mission_fallback_without_model_is_valid_pack():
    doc = SourceDoc(title='Ark Cluster Troubleshooting', content='cluster sync tips', source='mediawiki', source_id='1')
    c = Classification(title='Ark Cluster Troubleshooting', description='', source='mediawiki')
    out = transform_to_training_artifact(doc, c, 'bisectbot_mission', model=None)
    assert out.source == 'vainasherstudios_transform'
    assert out.raw_metadata['target_type'] == 'bisectbot_mission'
    assert out.raw_metadata['artifact_format'] == 'json'
    import json
    data = json.loads(out.content)
    assert validate_training_artifact('bisectbot_mission', data)
    assert data['contentType'] == 'bisectbot.trainingMission'
    assert 'NEEDS AUTHOR REVIEW' in data['quizzes'][0]['question']


def test_scenario_fallback_serialises_to_yaml():
    doc = SourceDoc(title='V Rising RCON', content='rcon commands', source='zendesk', source_id='2')
    c = Classification(title='V Rising RCON', description='', source='zendesk')
    out = transform_to_training_artifact(doc, c, 'ticketlab_scenario', model=None)
    assert out.raw_metadata['artifact_format'] == 'yaml'
    import yaml
    data = yaml.safe_load(out.content)
    assert validate_training_artifact('ticketlab_scenario', data)
    assert data['schema_version'] == 2


def test_quiz_fallback_without_model():
    doc = SourceDoc(title='Hytale Setup', content='setup steps', source='zendesk', source_id='3')
    c = Classification(title='Hytale Setup', description='', source='zendesk')
    out = transform_to_training_artifact(doc, c, 'quiz', model=None)
    import json
    data = json.loads(out.content)
    assert validate_training_artifact('quiz', data)
    assert data['questionType'] == 'multiple_choice'
