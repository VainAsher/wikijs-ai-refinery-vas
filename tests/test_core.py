from refinery.core import (
    SourceDoc, Classification, deterministic_classify, infer_source_org,
    source_governance, build_wiki_path, suggest_canonical_target, slugify,
    scan_sensitive, normalise_assumptions, merge_ai_classification,
    transform_to_vas, ollama_base_url, brand_tokens, reference_source_orgs,
    compute_confidence, interpret_confidence, scrub_findings, apply_redactions,
)


def test_scrub_findings_and_redact():
    text = ('Contact admin@example.com. AWS key AKIAIOSFODNN7EXAMPLE. '
            'github_token ghp_' + 'a' * 36 + '. Internal host 10.0.0.5.')
    findings = scrub_findings(text)
    kinds = {f.kind for f in findings}
    assert 'email' in kinds and 'aws_access_key' in kinds and 'github_token' in kinds
    # critical items carry the right severity and a masked preview (not the full secret)
    aws = next(f for f in findings if f.kind == 'aws_access_key')
    assert aws.severity == 'critical' and 'AKIAIOSFODNN7EXAMPLE' not in aws.preview
    # redacting the critical/high subset removes the literals and inserts placeholders
    redactable = [f for f in findings if f.severity in ('critical', 'high')]
    out = apply_redactions(text, redactable)
    assert 'AKIAIOSFODNN7EXAMPLE' not in out and 'ghp_' not in out
    assert '[REDACTED:aws_access_key]' in out
    assert 'admin@example.com' in out  # email was medium, not in the chosen subset


def test_compute_confidence_signals_and_bands():
    # A rich, label-authoritative, well-resolved doc should land in the 'high' band...
    strong = compute_confidence(label_authoritative=True, source_org_known=True,
                                service_known=True, top_service_hits=3, service_candidates=2,
                                doc_type_known=True, content_len=2000)
    assert strong >= 0.75 and interpret_confidence(strong) == 'high'
    # ...while a thin, unresolved doc should be low and clamped into range.
    weak = compute_confidence(content_len=20)
    assert 0.05 <= weak <= 1.0 and interpret_confidence(weak) in ('low', 'very_low')
    assert strong > weak


def test_classify_sets_real_confidence(taxonomy):
    # The classifier should produce a varying, computed confidence (not the old flat 0.35).
    rich = deterministic_classify(SourceDoc(
        title='Minecraft Server Restart Runbook',
        content='Restart the spigot server, check modpack, restore backup. ' * 20,
        source='employer_hosting', source_id='r1'), taxonomy)
    thin = deterministic_classify(SourceDoc(title='x', content='hi', source='mystery', source_id='t1'), taxonomy)
    assert rich.confidence > thin.confidence
    assert rich.confidence != 0.35


def test_slugify():
    assert slugify('Hello, World!') == 'hello-world'
    assert slugify('  Multiple   Spaces ') == 'multiple-spaces'
    assert slugify('') == 'untitled'


def test_normalise_assumptions_variants():
    # list of strings
    assert normalise_assumptions(['a', 'b']) == ['a', 'b']
    # list of {type,value} dicts (the llama3.2:3b shape that used to render raw)
    assert normalise_assumptions([{'type': 'X', 'value': 'keep this'}]) == ['keep this']
    # dict without value -> k: v join
    assert normalise_assumptions([{'foo': 'bar'}]) == ['foo: bar']
    # newline string
    assert normalise_assumptions('- one\n- two') == ['one', 'two']
    # falsy
    assert normalise_assumptions(None) == []
    assert normalise_assumptions([]) == []


def test_scan_sensitive_detects_secrets():
    pii, secrets, findings = scan_sensitive('contact me at a@b.com with your api_key please')
    assert pii == 'possible'
    assert secrets == 'possible'
    assert 'email' in findings and 'api_key_word' in findings
    # high-signal token bumps to 'likely'
    _, secrets2, _ = scan_sensitive('AKIAIOSFODNN7EXAMPLE')
    assert secrets2 == 'likely'


def test_infer_source_org_label_authoritative():
    # explicit import label wins over content sniffing
    d = SourceDoc(title='Random', content='nothing here', source='authentik')
    assert infer_source_org(d) == 'authentik'


def test_infer_source_org_short_alias_word_boundary():
    # 'vas' must not match inside 'canvas'
    d = SourceDoc(title='Canvas gradebook guide', content='instructure canvas lms', source='somewhere')
    assert infer_source_org(d) != 'vainasherstudios'


def test_host_label_classifies_and_governs(taxonomy):
    # Importing under a generic host label is authoritative; the service is still
    # inferred from content (not pinned to website_hosting), and reference governance
    # (non-canonical, rewrite-required) is applied for the employer_reference role.
    d = SourceDoc(title='How to Restart Your Minecraft Server',
                  content='Game server panel. Check modpack and spigot plugins.',
                  source='employer_hosting', source_id='m1')
    c = deterministic_classify(d, taxonomy)
    assert c.source_org == 'employer_hosting'
    assert c.source_role == 'employer_reference'
    assert c.service == 'minecraft'
    assert c.canonical is False
    assert c.reuse_policy == 'rewrite_required'


def test_vendor_doc_service_from_label(taxonomy):
    d = SourceDoc(title='SSO Setup', content='configure saml oidc oauth provider', source='authentik', source_id='a1')
    c = deterministic_classify(d, taxonomy)
    assert c.service == 'authentik'
    assert c.source_role == 'vendor_documentation'
    assert 'vendor-docs' in c.tags


def test_governance_reference_forces_non_canonical():
    c = Classification(title='t', description='', source='competitor_hosting_1')
    c.source_org = 'competitor_hosting_1'
    c.canonical = True
    c.authority = 'canonical'
    source_governance(c)
    assert c.canonical is False
    assert c.authority == 'imported_unreviewed'
    assert c.customer_safe is False


def test_unknown_org_requires_review():
    c = Classification(title='t', description='', source='mystery')
    c.source_org = 'unknown'
    source_governance(c)
    assert c.reuse_policy == 'review_required'


def test_build_wiki_path_import_vs_transform():
    c = Classification(title='My Doc', description='', source='competitor_hosting_1')
    c.source_org = 'competitor_hosting_1'
    assert build_wiki_path(c) == 'imports/competitor_hosting_1/my-doc'
    t = Classification(title='Draft', description='', source='vainasherstudios_transform')
    t.canonical_target = 'sops/minecraft/my-draft'
    assert build_wiki_path(t) == 'sops/minecraft/my-draft'


def test_merge_ai_validates_and_reasserts_governance(taxonomy):
    base = deterministic_classify(SourceDoc(title='x', content='hosting', source='competitor_hosting_1', source_id='1'), taxonomy)
    # AI tries to set an invalid doc_type and mark a competitor doc canonical
    ai = {'doc_type': 'not_a_real_type', 'service': 'minecraft', 'canonical': True, 'authority': 'canonical'}
    merged = merge_ai_classification(base, ai, taxonomy)
    assert merged.doc_type != 'not_a_real_type'   # invalid rejected
    assert merged.service == 'minecraft'           # valid accepted
    assert merged.canonical is False               # governance reasserts on reference org


def test_transform_fallback_without_model():
    d = SourceDoc(title='Ban Appeals', content='moderator reviews report', source='competitor_hosting_1', source_id='1')
    c = Classification(title='Ban Appeals', description='', source='competitor_hosting_1')
    c.source_org = 'competitor_hosting_1'
    out = transform_to_vas(d, c, 'rewrite_into_moderation_playbook', model=None)
    assert out.source == 'vainasherstudios_transform'
    assert 'Draft generated for human review' in out.content   # deterministic fallback path
    assert out.title.startswith('VAS Draft')


def test_ollama_base_url():
    assert ollama_base_url('http://localhost:11434/api/generate') == 'http://localhost:11434'
    assert ollama_base_url('https://host:9000/api/x') == 'https://host:9000'
    assert ollama_base_url('') == 'http://localhost:11434'


def test_reference_orgs_exclude_owned():
    refs = reference_source_orgs()
    assert 'competitor_hosting_1' in refs
    assert 'vainasherstudios' not in refs
