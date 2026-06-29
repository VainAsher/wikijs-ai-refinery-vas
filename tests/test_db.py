import json, sqlite3, datetime as dt
from refinery.core import SourceDoc, Classification, deterministic_classify, build_wiki_path
from refinery.db import Store, import_key_for, DocNotFound, DENORM_FIELDS


def _doc(title='Doc', content='minecraft spigot', source='employer_hosting', sid='1'):
    return SourceDoc(title=title, content=content, source=source, source_id=sid)


def _add(store, taxonomy, **kw):
    d = _doc(**kw)
    c = deterministic_classify(d, taxonomy)
    return store.add_doc(d, c, build_wiki_path(c), import_key=import_key_for(d)), c


def test_add_and_get(store, taxonomy):
    doc_id, _ = _add(store, taxonomy)
    row = store.get_doc(doc_id)
    assert row['title'] == 'Doc'
    assert store.count_docs() == 1


def test_get_missing_raises_docnotfound(store):
    try:
        store.get_doc(99999)
        assert False, 'expected DocNotFound'
    except DocNotFound:
        pass


def test_dedup_same_source_id(store, taxonomy):
    id1, _ = _add(store, taxonomy, sid='same')
    id2, _ = _add(store, taxonomy, sid='same')
    assert id1 == id2
    assert store.count_docs() == 1


def test_reimport_updates_needs_review_not_reviewed(store, taxonomy):
    d = _doc(content='original minecraft')
    c = deterministic_classify(d, taxonomy)
    doc_id = store.add_doc(d, c, build_wiki_path(c), import_key=import_key_for(d))
    # mark reviewed
    c.review_status = 'reviewed'
    store.update_doc(doc_id, c, build_wiki_path(c))
    # re-import with new content must NOT overwrite reviewed work
    d2 = _doc(content='changed content')
    c2 = deterministic_classify(d2, taxonomy)
    store.add_doc(d2, c2, build_wiki_path(c2), import_key=import_key_for(d2))
    assert 'original' in store.get_doc(doc_id)['content']


def test_indexed_filters(store, taxonomy):
    _add(store, taxonomy, source='employer_hosting', content='minecraft spigot', sid='a')
    _add(store, taxonomy, source='authentik', content='saml oidc', sid='b')
    assert store.count_docs(source_org='employer_hosting') == 1
    assert store.count_docs(source_org='authentik') == 1
    assert store.count_docs(service='authentik') == 1
    assert store.count_docs(source_org='nonexistent') == 0


def test_wildcard_escaping(store, taxonomy):
    _add(store, taxonomy, title='Plain title', content='nothing special', sid='a')
    # A literal % must be treated literally, not as match-all
    assert store.count_docs(q='100%') == 0
    assert store.count_docs(q='Plain') == 1


def test_breakdown_groups(store, taxonomy):
    _add(store, taxonomy, source='employer_hosting', content='minecraft', sid='a')
    _add(store, taxonomy, source='competitor_hosting_1', content='minecraft', sid='b')
    bd = dict(store.breakdown('source_org'))
    assert bd.get('employer_hosting') == 1 and bd.get('competitor_hosting_1') == 1


def test_breakdown_rejects_bad_field(store):
    try:
        store.breakdown('content')   # not whitelisted -> injection guard
        assert False, 'expected ValueError'
    except ValueError:
        pass


def test_counts_use_indexed_columns(store, taxonomy):
    _add(store, taxonomy, source='competitor_hosting_1', content='minecraft', sid='a')
    counts = store.counts()
    assert counts['total'] == 1
    assert counts['source_org:competitor_hosting_1'] == 1
    assert counts['rewrite_status:needs_rewrite'] == 1


def test_migration_backfills_old_db(tmp_path, taxonomy):
    # Build a pre-migration DB: docs table with neither import_key nor denorm columns.
    path = tmp_path / 'old.sqlite3'
    conn = sqlite3.connect(path)
    conn.execute('''CREATE TABLE docs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,title TEXT NOT NULL,source TEXT NOT NULL,source_id TEXT,
        source_url TEXT,original_updated_at TEXT,content TEXT NOT NULL,raw_metadata_json TEXT NOT NULL DEFAULT '{}',
        classification_json TEXT NOT NULL,review_status TEXT NOT NULL DEFAULT 'needs_review',wiki_path TEXT,
        published INTEGER NOT NULL DEFAULT 0,publish_message TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL)''')
    c = Classification(title='Legacy', description='', source='competitor_hosting_1')
    c.source_org = 'competitor_hosting_1'; c.service = 'minecraft'; c.doc_type = 'runbook'
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    conn.execute('INSERT INTO docs (title,source,content,classification_json,review_status,wiki_path,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?)',
                 ('Legacy', 'competitor_hosting_1', 'x', json.dumps({**c.__dict__}), 'needs_review', 'imports/competitor_hosting_1/legacy', now, now))
    conn.commit(); conn.close()

    # Opening with the new Store must add + backfill the denorm columns transparently.
    store = Store(str(path))
    cols = {r[1] for r in store.conn.execute('PRAGMA table_info(docs)')}
    for f in DENORM_FIELDS:
        assert f in cols
    assert store.count_docs(source_org='competitor_hosting_1') == 1
    assert store.count_docs(service='minecraft') == 1


def test_run_history_and_summary(store):
    store.add_run(source_doc_id=1, new_doc_id=2, target_action='rewrite_into_sop', model='mistral:latest',
                  dials={'tone': 'professional'}, brand_score=84, latency_ms=1200)
    store.add_run(source_doc_id=3, new_doc_id=4, target_action='rewrite_into_runbook', model='',
                  dials={}, brand_score=92, latency_ms=400)
    runs = store.list_runs()
    assert len(runs) == 2 and runs[0]['new_doc_id'] == 4   # newest first
    s = store.run_summary()
    assert s['count'] == 2 and s['with_model'] == 1
    assert s['avg_brand_score'] == 88.0 and s['avg_latency_ms'] == 800


def test_import_key_none_without_source_id():
    assert import_key_for(SourceDoc(title='t', content='c', source='s', source_id='')) is None
    assert import_key_for(SourceDoc(title='t', content='c', source='s', source_id='x')) is not None
