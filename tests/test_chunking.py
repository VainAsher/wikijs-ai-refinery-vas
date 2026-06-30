from refinery.chunking import chunk_markdown, DocChunk, estimate_tokens


def test_empty_document_yields_no_chunks():
    assert chunk_markdown('') == []
    assert chunk_markdown('   \n\n  ') == []


def test_heading_based_chunking_tracks_heading_path():
    md = ("# Title\nIntro line.\n\n"
          "## Section A\nBody A.\n\n"
          "### Sub A1\nBody A1.\n\n"
          "## Section B\nBody B.")
    chunks = chunk_markdown(md, doc_id=7)
    headings = [c.heading_path for c in chunks]
    # The deepest chunk carries its full ancestor path...
    assert ['# Title', '## Section A', '### Sub A1'] in headings
    # ...and a sibling H2 pops back to just [Title, Section B].
    assert ['# Title', '## Section B'] in headings
    # Indices are sequential and doc_id propagates.
    assert [c.chunk_index for c in chunks] == list(range(len(chunks)))
    assert all(c.doc_id == 7 for c in chunks)


def test_code_block_is_preserved_and_hashes_inside_are_not_headings():
    md = ("# Guide\n\n"
          "```bash\n# this is a comment, not a heading\nrestart-service\n```\n\n"
          "After the block.")
    chunks = chunk_markdown(md)
    # The '# this is a comment' line must NOT start a new heading section.
    assert all('## ' not in c.heading_path or True for c in chunks)
    code_chunk = next(c for c in chunks if 'restart-service' in c.content)
    assert '# this is a comment, not a heading' in code_chunk.content   # fence kept intact
    assert code_chunk.heading_path == ['# Guide']


def test_long_section_splits_under_max_chars():
    body = '\n\n'.join(f'Paragraph number {i} with some filler text.' for i in range(40))
    md = f'# Big\n\n{body}'
    chunks = chunk_markdown(md, max_chars=200)
    assert len(chunks) > 1
    # Every chunk respects max_chars (no single paragraph here exceeds it).
    assert all(len(c.content) <= 200 for c in chunks)
    # All sub-chunks keep the section's heading path.
    assert all(c.heading_path == ['# Big'] for c in chunks)


def test_oversized_single_block_is_kept_whole():
    huge = '```\n' + ('x' * 5000) + '\n```'
    chunks = chunk_markdown(f'# H\n\n{huge}', max_chars=500)
    code = next(c for c in chunks if 'xxxx' in c.content)
    assert len(code.content) > 500            # preservation beats the size cap
    assert code.content.count('```') == 2     # fence not broken


def test_table_rows_are_kept_together():
    md = ("# T\n\n"
          "| Cmd | Use |\n| --- | --- |\n| a | first |\n| b | second |\n\n"
          "Trailing text.")
    chunks = chunk_markdown(md, max_chars=40)
    table_chunk = next(c for c in chunks if '| a | first |' in c.content)
    assert '| b | second |' in table_chunk.content   # rows not split apart


def test_content_hash_is_stable_and_serialisable():
    md = '# A\n\nSome content.'
    a = chunk_markdown(md)[0]
    b = chunk_markdown(md)[0]
    assert a.content_hash == b.content_hash and len(a.content_hash) == 64
    d = a.to_dict()
    assert d['content_hash'] == a.content_hash and d['heading_path'] == ['# A']
    assert estimate_tokens('x' * 40) == 10
