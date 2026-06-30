from refinery.retrieval import RetrievalIndex, keyword_rank


def test_keyword_rank_orders_by_overlap_and_respects_limit():
    chunks = ['nothing relevant here', 'DNS SPF DKIM email authentication', 'email setup basics']
    ranked = keyword_rank('how do I configure SPF for email', chunks, limit=2)
    assert ranked[0] == 'DNS SPF DKIM email authentication'   # best overlap first
    assert len(ranked) == 2                                    # limit respected


def test_index_and_search_offline(store):
    idx = RetrievalIndex(store)                                # no embedder -> deterministic
    chunks = idx.index_doc(11, '# Email\nConfigure SPF and DKIM.\n\n# Backups\nRestore from snapshot nightly.')
    assert chunks and store.get_doc_chunks(11)                 # indexed + stored

    hits = idx.search('how do I restore a backup snapshot', limit=3)
    assert hits and 'snapshot' in hits[0].content.lower()      # most relevant chunk first
    assert all('snapshot' in h.content.lower() or 'restore' in h.content.lower() for h in hits)


def test_search_returns_empty_when_nothing_matches(store):
    idx = RetrievalIndex(store)
    idx.index_doc(12, '# Email\nConfigure SPF and DKIM.')
    assert idx.search('kubernetes helm chart rollout', limit=5) == []


def test_search_can_filter_by_doc(store):
    idx = RetrievalIndex(store)
    idx.index_doc(1, '# A\nspecial alpha keyword content')
    idx.index_doc(2, '# B\nspecial beta keyword content')
    hits = idx.search('special keyword', filters={'doc_id': 2}, limit=10)
    assert hits and all(h.doc_id == 2 for h in hits)
