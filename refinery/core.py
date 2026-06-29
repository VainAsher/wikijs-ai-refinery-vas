from __future__ import annotations
import dataclasses, datetime as dt, json, os, re
from typing import Any, Dict, List, Optional, Tuple
import requests, yaml

DEFAULT_TAXONOMY = {
 'doc_types':['sop','runbook','policy','how_to','troubleshooting','faq','customer_template','internal_note','architecture','iac_reference','service_overview','incident_report','postmortem','checklist','training','glossary','decision_record','draft','moderation_playbook','training_module','lesson_plan','content_script','social_post_template','community_announcement','incident_response','admin_guide','stream_outline','discord_staff_guide','unknown'],
 'audiences':['public','customer','internal','admin_only','private','community_member','moderator','admin','trainee','content_audience','unknown'],
 'authorities':['canonical','approved','imported_unreviewed','draft','deprecated','conflicting','archived','unknown'],
 'risk_levels':['low','medium','high','critical'],
 'review_statuses':['needs_review','reviewed','rejected'],
 'services':['website_hosting','website_development','managed_it','business_email','ai_workflows','automation','wordpress','nextcloud','invoice_ninja','mailcow','authentik','traefik','cloudflare','proxmox','backup','monitoring','billing','pterodactyl','minecraft','project_zomboid','rust','discord','twitch','youtube','linkedin','canvas','gaming_community_management','moderator_training','admin_training','game_server_hosting','unknown'],
 'domains':['vain_asher_studios','client','community','personal','household','wedding','employer_hosting','game_dev','managed_it','web_hosting','web_development','ai_workflows','gaming_community_ops','moderator_training','content_creation','game_server_hosting','unknown'],
 'source_orgs':['vainasherstudios','employer_hosting','competitor_hosting_1','competitor_hosting_2','infrastructure_provider_1','infrastructure_provider_2','authentik','pterodactyl','rust','canvas','traefik','mailcow','nextcloud','proxmox','cloudflare','invoice_ninja','wikijs','zammad','vaultwarden','paperless','forgejo','documenso','coolify','n8n','client','internal','community_reference','unknown'],
 'source_roles':['canonical','owned','reference_only','evidence','imported_source','competitor_reference','employer_reference','infrastructure_reference','vendor_documentation','community_reference','training_reference','unknown'],
 'reuse_policies':['owned_original','rewrite_required','reference_only','quote_prohibited','review_required','forbidden','owned_training_material','unknown'],
 'adaptation_actions':['none','reference_only','rewrite_into_sop','rewrite_into_runbook','rewrite_into_customer_guide','rewrite_into_support_template','rewrite_into_policy','rewrite_into_training','rewrite_into_moderation_playbook','rewrite_into_admin_guide','rewrite_into_lesson_plan','rewrite_into_youtube_script','rewrite_into_linkedin_post','rewrite_into_twitch_outline','rewrite_into_discord_staff_guide','rewrite_into_community_announcement','gap_analysis_only','reject_archive'],
 'rewrite_statuses':['not_required','needs_rewrite','draft_generated','in_review','approved','rejected'],
}

WIKIJS_CREATE_MUTATION = '''
mutation ($content: String!, $description: String!, $editor: String!, $isPublished: Boolean!, $locale: String!, $path: String!, $tags: [String]!, $title: String!) {
  pages { create(content: $content, description: $description, editor: $editor, isPublished: $isPublished, locale: $locale, path: $path, tags: $tags, title: $title) { responseResult { succeeded message } } }
}
'''

@dataclasses.dataclass
class SourceDoc:
    title: str
    content: str
    source: str
    source_id: str = ''
    source_url: str = ''
    original_updated_at: str = ''
    raw_metadata: Dict[str, Any] = dataclasses.field(default_factory=dict)

@dataclasses.dataclass
class Classification:
    title: str
    description: str
    source: str
    source_id: str = ''
    source_url: str = ''
    imported_at: str = dataclasses.field(default_factory=lambda: dt.datetime.now(dt.timezone.utc).isoformat())
    original_updated_at: str = ''
    owner: str = ''
    domain: str = 'vain_asher_studios'
    service: str = 'unknown'
    system: str = 'unknown'
    doc_type: str = 'unknown'
    audience: str = 'unknown'
    customer_safe: bool = False
    authority: str = 'imported_unreviewed'
    risk_level: str = 'medium'
    contains_pii: str = 'unknown'
    contains_secrets: str = 'unknown'
    lifecycle: str = 'active_candidate'
    review_status: str = 'needs_review'
    reviewed_by: str = ''
    last_reviewed: str = ''
    review_cycle_days: int = 90
    canonical: bool = False
    supersedes: List[str] = dataclasses.field(default_factory=list)
    superseded_by: str = ''
    related_docs: List[str] = dataclasses.field(default_factory=list)
    summary: str = ''
    tags: List[str] = dataclasses.field(default_factory=list)
    confidence: float = 0.0
    reasons: List[str] = dataclasses.field(default_factory=list)
    # VainAsherStudios refinery upgrade
    business_owner: str = 'VainAsherStudios'
    source_org: str = 'unknown'
    source_role: str = 'imported_source'
    reuse_policy: str = 'rewrite_required'
    adaptation_action: str = 'reference_only'
    canonical_target: str = ''
    rewrite_status: str = 'needs_rewrite'
    transform_source_doc_id: str = ''
    transform_notes: str = ''

def load_taxonomy(path: Optional[str]) -> Dict[str, List[str]]:
    merged = dict(DEFAULT_TAXONOMY)
    if path:
        with open(path,'r',encoding='utf-8') as f: merged.update(yaml.safe_load(f) or {})
    return merged

def slugify(v: str, fallback='untitled') -> str:
    v=(v or '').lower().strip(); v=re.sub(r'[^a-z0-9\s-]','',v); v=re.sub(r'[\s_]+','-',v); v=re.sub(r'-+','-',v).strip('-'); return v or fallback

def clean_markdown(c: str) -> str:
    c=re.sub(r'\n{4,}','\n\n\n',c or ''); c=re.sub(r'\[edit\]','',c,flags=re.I); c=re.sub(r'<!--.*?-->','',c,flags=re.S); return c.strip()+'\n'

def scan_sensitive(content: str)->Tuple[str,str,List[str]]:
    pats={'email':r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b','uk_phone_possible':r'\b(?:\+44\s?7\d{3}|07\d{3})\s?\d{3}\s?\d{3}\b','ipv4':r'\b(?:\d{1,3}\.){3}\d{1,3}\b','api_key_word':r'(?i)\b(api[_-]?key|secret|token|password|passwd|private[_-]?key|client[_-]?secret)\b','aws_key_possible':r'\bAKIA[0-9A-Z]{16}\b','github_token_possible':r'\bgh[pousr]_[A-Za-z0-9_]{20,}\b','jwt_possible':r'\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b'}
    findings=[n for n,p in pats.items() if re.search(p,content or '')]
    pii='possible' if any(x in findings for x in ['email','uk_phone_possible','ipv4']) else 'false'
    secrets='possible' if any(x in findings for x in ['api_key_word','aws_key_possible','github_token_possible','jwt_possible']) else 'false'
    if any(x in findings for x in ['aws_key_possible','github_token_possible','jwt_possible']): secrets='likely'
    return pii,secrets,findings

def compute_confidence(*, label_authoritative: bool=False, source_org_known: bool=False,
                       service_known: bool=False, top_service_hits: int=0, service_candidates: int=0,
                       doc_type_known: bool=False, content_len: int=0) -> float:
    """Deterministic 0..1 confidence in the auto-classification, from how much real
    signal we actually had (adapted from CrucibleOS's confidence model). Strong, named
    signals (an authoritative import label, multiple keyword hits, a resolved doc_type)
    raise it; thin or ambiguous input lowers it. This replaces the old flat 0.35 so the
    review queue can surface low-confidence docs for human attention first."""
    score = 0.40  # baseline for any deterministic pass
    if label_authoritative:      score += 0.20   # org came from an exact, trusted import label
    elif source_org_known:       score += 0.10   # org inferred from content/url
    if service_known:            score += 0.10 + min(top_service_hits, 3) * 0.05  # more keyword hits => surer
    if doc_type_known:           score += 0.08
    if service_candidates > 1:   score += 0.05   # corroborating signals across services
    if content_len < 200:        score -= 0.15   # too little text to trust the call
    if not service_known and not doc_type_known: score -= 0.10  # nothing concrete resolved
    return round(max(0.05, min(1.0, score)), 2)

def interpret_confidence(score: float) -> str:
    """Human-readable band for a 0..1 confidence score."""
    if score >= 0.75: return 'high'
    if score >= 0.50: return 'medium'
    if score >= 0.30: return 'low'
    return 'very_low'

# ---------------------------------------------------------------------------
# Source registry
# ---------------------------------------------------------------------------
# Single source of truth for "where did this doc come from, and how are we
# allowed to use it". Adding a new provider is one entry here plus one line in
# taxonomy.yml -> source_orgs. No if/elif edits needed.
#
# Fields:
#   aliases : substrings (lowercased) used to detect the org from source/url/title.
#   role/reuse/adaptation/rewrite : governance defaults applied on import.
#   reference : True => never canonical, never customer_safe, force imported_unreviewed.
# ---------------------------------------------------------------------------
SOURCE_REGISTRY: Dict[str, Dict[str, Any]] = {
    'vainasherstudios': {
        'aliases': ['vainasherstudios', 'vain asher', 'vas'],
        'role': 'owned', 'reuse': 'owned_original',
        'adaptation': 'none', 'rewrite': 'not_required', 'reference': False,
    },
    # Hosting providers are referenced by generic, anonymised category slugs rather
    # than real brand names. The role still encodes the relationship (the employer we
    # worked for vs. competing SME hosts), which is what governance keys off. Assign
    # the right slug at import time via the label|path field — there are no brand
    # aliases to auto-detect from content, by design.
    'employer_hosting': {
        'aliases': ['employer_hosting'],
        'role': 'employer_reference', 'reuse': 'rewrite_required',
        'adaptation': 'reference_only', 'rewrite': 'needs_rewrite', 'reference': True, 'strip_brand': True,
    },
    'competitor_hosting_1': {
        'aliases': ['competitor_hosting_1'],
        'role': 'competitor_reference', 'reuse': 'rewrite_required',
        'adaptation': 'reference_only', 'rewrite': 'needs_rewrite', 'reference': True, 'strip_brand': True,
    },
    'competitor_hosting_2': {
        'aliases': ['competitor_hosting_2'],
        'role': 'competitor_reference', 'reuse': 'rewrite_required',
        'adaptation': 'reference_only', 'rewrite': 'needs_rewrite', 'reference': True, 'strip_brand': True,
    },
    # Infrastructure/cloud suppliers VAS builds on (not SME-hosting competitors) are
    # likewise referenced by generic, anonymised slugs. The infrastructure_reference
    # role keeps them distinct from the hosting competitors above. Assign at import
    # time via the label|path field; no brand aliases are auto-detected from content.
    'infrastructure_provider_1': {
        'aliases': ['infrastructure_provider_1'],
        'role': 'infrastructure_reference', 'reuse': 'rewrite_required',
        'adaptation': 'reference_only', 'rewrite': 'needs_rewrite', 'reference': True,
    },
    'infrastructure_provider_2': {
        'aliases': ['infrastructure_provider_2'],
        'role': 'infrastructure_reference', 'reuse': 'rewrite_required',
        'adaptation': 'reference_only', 'rewrite': 'needs_rewrite', 'reference': True,
    },
}

# ---------------------------------------------------------------------------
# Managed-service documentation sources
# ---------------------------------------------------------------------------
# Official documentation for any tool/service VAS manages, operates, or maintains
# (Authentik, Pterodactyl, Rust, Canvas, and the wider self-hosted stack). These
# are *reference* sources with a distinct posture: adapt them into VAS-owned
# runbooks/SOPs, never republish verbatim, and respect the upstream licence.
#
# The slug doubles as the 'service' when it matches the services taxonomy
# (Authentik docs are about Authentik), so service classification is driven by the
# source label rather than fragile keyword guessing. Add a new tool's docs by
# appending one line here (and, if you want it in the UI dropdowns, one line in
# taxonomy.yml -> source_orgs).
MANAGED_SERVICE_DOC_ORGS: Dict[str, List[str]] = {
    'authentik':     ['authentik', 'goauthentik'],
    'pterodactyl':   ['pterodactyl', 'wings panel'],
    'rust':          ['rust server', 'rust admin', 'oxide', 'umod', 'facepunch'],
    'canvas':        ['canvas lms', 'instructure'],
    'traefik':       ['traefik'],
    'mailcow':       ['mailcow'],
    'nextcloud':     ['nextcloud'],
    'proxmox':       ['proxmox ve', 'proxmox'],
    'cloudflare':    ['cloudflare'],
    'invoice_ninja': ['invoice ninja', 'invoiceninja'],
    'wikijs':        ['wiki.js', 'wikijs'],
    'zammad':        ['zammad'],
    'vaultwarden':   ['vaultwarden'],
    'paperless':     ['paperless-ngx', 'paperless'],
    'forgejo':       ['forgejo'],
    'documenso':     ['documenso'],
    'coolify':       ['coolify'],
    'n8n':           ['n8n'],
}
VENDOR_DOC_PROFILE: Dict[str, Any] = {
    'role': 'vendor_documentation', 'reuse': 'rewrite_required',
    'adaptation': 'reference_only', 'rewrite': 'needs_rewrite', 'reference': True,
}
for _slug, _aliases in MANAGED_SERVICE_DOC_ORGS.items():
    # Don't clobber an explicit registry entry if a slug overlaps (none do today).
    SOURCE_REGISTRY.setdefault(_slug, {'aliases': _aliases, **VENDOR_DOC_PROFILE})

# Detection order: longest org keys / most specific first so that, e.g., a doc
# mentioning both never gets mis-bucketed by a short alias winning by position.
_REGISTRY_ORDER = sorted(SOURCE_REGISTRY, key=lambda k: -len(k))

def reference_source_orgs() -> List[str]:
    """Orgs whose content is reference-only (used for dashboards/counters)."""
    return [k for k, v in SOURCE_REGISTRY.items() if v.get('reference')]

def brand_tokens() -> List[str]:
    """Host-provider label strings stripped from text before service keyword scoring,
    so a hosting org's own slug can't by itself trigger the 'hosting' service. Only
    entries flagged strip_brand contribute — tool names like 'authentik' or
    'pterodactyl' must stay in, since they're exactly what we want to match on."""
    toks = set()
    for v in SOURCE_REGISTRY.values():
        if v.get('strip_brand'):
            toks.update(v['aliases'])
    return sorted(toks, key=lambda s: -len(s))  # longest-first for stable, greedy stripping

def infer_source_org(doc: SourceDoc) -> str:
    # The import label is authoritative: if a doc was imported as 'authentik' or
    # 'infrastructure_provider_1', trust that over content sniffing (this is the whole
    # point of the label|path system, and avoids a doc that merely *mentions* Proxmox
    # being mis-attributed away from its real source).
    label = (doc.source or '').strip().lower()
    if label in SOURCE_REGISTRY:
        return label
    hay = f"{doc.source} {doc.source_url} {doc.title}".lower()
    for org in _REGISTRY_ORDER:
        for alias in SOURCE_REGISTRY[org]['aliases']:
            # Short aliases must match as whole words to avoid false positives
            # (e.g. 'vas' inside 'canvas', or a short slug inside a longer token).
            if len(alias) < 4:
                if re.search(rf'\b{re.escape(alias)}\b', hay):
                    return org
            elif alias in hay:
                return org
    return 'unknown'

def source_governance(c: Classification) -> None:
    entry = SOURCE_REGISTRY.get(c.source_org)
    if not entry:
        c.source_role = 'imported_source'; c.reuse_policy = 'review_required'
        c.adaptation_action = 'reference_only'; c.rewrite_status = 'needs_rewrite'
        return
    c.source_role = entry['role']; c.reuse_policy = entry['reuse']
    c.adaptation_action = entry['adaptation']; c.rewrite_status = entry['rewrite']
    if entry.get('reference'):
        c.canonical = False; c.authority = 'imported_unreviewed'; c.customer_safe = False

def deterministic_classify(doc: SourceDoc, taxonomy: Dict[str,List[str]]) -> Classification:
    text=f"{doc.title}\n{doc.content[:10000]}".lower()
    c=Classification(title=doc.title or 'Untitled', description=f'Imported from {doc.source}', source=doc.source, source_id=doc.source_id, source_url=doc.source_url, original_updated_at=doc.original_updated_at, tags=[f'{doc.source}-import','needs-review'], confidence=.35, reasons=['Baseline deterministic classification applied.'])
    c.source_org=infer_source_org(doc); source_governance(c)
    # Strip the resolved provider's label from the text before service scoring, so a
    # hosting org's slug can't by itself trip the website_hosting keyword 'hosting'
    # (the bug that pinned most imported docs to website_hosting).
    svc_text=text
    for tok in brand_tokens(): svc_text=svc_text.replace(tok,' ')
    services={'website_hosting':['hosting','cpanel','plesk','site','website','ssl','dns'],'website_development':['wordpress','elementor','theme','plugin','site build'],'managed_it':['managed it','endpoint','device','backup','support'],'business_email':['mailbox','email','smtp','imap','mx record','spf','dkim','dmarc'],'ai_workflows':['ai workflow','automation','n8n','zapier','agent','ollama'],'pterodactyl':['pterodactyl','wings','egg'],'minecraft':['minecraft','spigot','paper','forge','fabric','modpack'],'project_zomboid':['project zomboid','zomboid','pzwiki'],'rust':['rust server','oxide','umod','rust game'],'discord':['discord','moderator','modlog','ban appeal','community rule'],'gaming_community_management':['community','moderation','admin','player report','ban','appeal'],'moderator_training':['moderator training','train moderators','staff training'],'youtube':['youtube','video script','thumbnail'],'twitch':['twitch','stream outline'],'linkedin':['linkedin','professional post'],'cloudflare':['cloudflare','dns record','tunnel'],'wordpress':['wordpress','wp-admin','elementor'],'mailcow':['mailcow','postfix','dovecot'],'proxmox':['proxmox','pve','lxc'],'authentik':['authentik','sso','saml','oidc','oauth','identity provider'],'nextcloud':['nextcloud','collabora'],'traefik':['traefik','reverse proxy','middleware'],'invoice_ninja':['invoice ninja','invoiceninja'],'canvas':['canvas lms','instructure','gradebook']}
    # Score every service by keyword hits and pick the strongest, instead of letting
    # whichever service is listed first win. Ties fall back to taxonomy order for stability.
    _svc_order=list(services)
    scores={svc:sum(1 for k in kws if k in svc_text) for svc,kws in services.items()}
    ranked=sorted([(svc,n) for svc,n in scores.items() if n>0], key=lambda x:(-x[1], _svc_order.index(x[0])))
    services_tax=taxonomy.get('services',[])
    if c.source_org in services_tax:
        # A managed tool's own documentation is about that tool: the source label is
        # the strongest signal (Authentik docs -> service=authentik), overriding keyword
        # noise. Keyword-matched services are still kept as secondary tags.
        c.service=c.source_org
        for svc,_n in [(c.source_org,0)]+ranked:
            if svc not in c.tags: c.tags.append(svc)
    elif ranked:
        c.service=ranked[0][0]
        for svc,_n in ranked:  # multi-topic docs keep every matched service as a tag
            if svc not in c.tags: c.tags.append(svc)
    if len(ranked)>1:
        c.reasons.append('Service candidates (by keyword hits): '+', '.join(f'{s}:{n}' for s,n in ranked[:4]))
    if c.source_role=='vendor_documentation':
        c.reasons.append('Upstream tool documentation: adapt into VAS-owned runbooks/SOPs, do not republish verbatim, and check the upstream licence.')
        if 'vendor-docs' not in c.tags: c.tags.append('vendor-docs')
    if any(w in text for w in ['restore','restart','rotate','rollback','rebuild','incident','outage']): c.doc_type='runbook'
    elif any(w in text for w in ['policy','acceptable use','retention','gdpr']): c.doc_type='policy'
    elif any(w in text for w in ['troubleshoot','error','crash','failed','cannot connect']): c.doc_type='troubleshooting'
    elif any(w in text for w in ['terraform','ansible','docker compose','docker-compose','cloud-init']): c.doc_type='iac_reference'
    elif any(w in text for w in ['moderator','ban appeal','player report','community rule','staff training']): c.doc_type='moderation_playbook'
    elif any(w in text for w in ['youtube script','video outline','twitch','linkedin post','discord announcement']): c.doc_type='content_script'
    elif any(w in text for w in ['template','reply','customer update','email']): c.doc_type='customer_template'
    elif any(w in text for w in ['how to','guide','steps']): c.doc_type='how_to'
    c.tags.append(c.doc_type)
    c.audience='customer' if any(w in text for w in ['you can','your server','your website','customer']) else 'internal'
    if any(w in text for w in ['delete','drop database','wipe','rm -rf','rotate secret','private key','firewall','billing']): c.risk_level='critical'
    elif any(w in text for w in ['restore','backup','database','production','restart','dns','ssl']): c.risk_level='high'
    elif any(w in text for w in ['config','settings','install','update']): c.risk_level='medium'
    else: c.risk_level='low'
    pii,secrets,findings=scan_sensitive(doc.content); c.contains_pii=pii; c.contains_secrets=secrets
    if findings: c.tags.append('sensitive-scan-hit'); c.reasons.append('Sensitive scanner findings: '+', '.join(findings)); c.customer_safe=False
    if c.risk_level in ['high','critical']: c.reasons.append('Risk level requires human review.')
    c.confidence=compute_confidence(
        label_authoritative=(c.source_org!='unknown' and (doc.source or '').strip().lower()==c.source_org),
        source_org_known=(c.source_org!='unknown'),
        service_known=(c.service!='unknown'),
        top_service_hits=(ranked[0][1] if ranked else 0),
        service_candidates=len(ranked),
        doc_type_known=(c.doc_type!='unknown'),
        content_len=len(doc.content or ''),
    )
    c.reasons.append(f'Classification confidence: {interpret_confidence(c.confidence)} ({c.confidence:.2f}).')
    c.canonical_target=suggest_canonical_target(c)
    return c

def suggest_canonical_target(c: Classification) -> str:
    slug=slugify(c.title)
    action_map={'rewrite_into_sop':'sops','rewrite_into_runbook':'runbooks','rewrite_into_policy':'policies','rewrite_into_customer_guide':'guides','rewrite_into_support_template':'templates/support-replies','rewrite_into_training':'training','rewrite_into_moderation_playbook':'community/moderation-playbooks','rewrite_into_admin_guide':'community/admin-guides','rewrite_into_lesson_plan':'training/lesson-plans','rewrite_into_youtube_script':'content/youtube','rewrite_into_linkedin_post':'content/linkedin','rewrite_into_twitch_outline':'content/twitch','rewrite_into_discord_staff_guide':'community/discord-staff-guides','rewrite_into_community_announcement':'community/announcements'}
    base=action_map.get(c.adaptation_action,'reference')
    if base in ['policies','reference']: return f'{base}/{slug}'
    return f'{base}/{c.service}/{slug}'

def normalise_assumptions(value: Any) -> List[str]:
    """Coerce whatever the model returned for 'assumptions' into a clean list of
    strings. Models are inconsistent: some return a list of strings, some a list of
    {'type','value'} dicts, some a single newline-joined string, some None. Without
    this, a dict assumption rendered as the literal "- {'type': ...}" in the draft
    (observed with llama3.2:3b)."""
    if not value:
        return []
    if isinstance(value, str):
        items = [v.strip(' -*') for v in value.splitlines()]
    elif isinstance(value, dict):
        items = [f'{k}: {v}' for k, v in value.items()]
    elif isinstance(value, (list, tuple)):
        items = []
        for v in value:
            if isinstance(v, dict):
                # Prefer a human-readable value field; fall back to k: v pairs.
                label = v.get('value') or v.get('assumption') or v.get('text')
                items.append(str(label) if label else ', '.join(f'{k}: {val}' for k, val in v.items()))
            else:
                items.append(str(v))
    else:
        items = [str(value)]
    return [i for i in (s.strip() for s in items) if i]

def ollama_json(prompt: str, model: str, url='http://localhost:11434/api/generate', timeout: int = 180) -> Optional[Dict[str,Any]]:
    try:
        r=requests.post(url,json={'model':model,'prompt':prompt,'stream':False,'format':'json'},timeout=timeout); r.raise_for_status(); return json.loads(r.json().get('response','{}'))
    except Exception: return None

def ollama_base_url(generate_url: str) -> str:
    """Derive the Ollama server root (http://host:port) from a /api/... endpoint URL,
    so health/model lookups share whatever the user configured for generation."""
    m = re.match(r'(https?://[^/]+)', generate_url or '')
    return m.group(1) if m else 'http://localhost:11434'

def ollama_status(generate_url='http://localhost:11434/api/generate', timeout: int = 4) -> Dict[str, Any]:
    """Live health probe of the local Ollama server: reachability, installed models
    (name + size), and currently loaded models. Used by the monitoring/config pages.
    Never raises — returns {'up': False, 'error': ...} when the server is unreachable."""
    base = ollama_base_url(generate_url)
    try:
        tags = requests.get(f'{base}/api/tags', timeout=timeout); tags.raise_for_status()
        models = [{'name': m.get('name', ''), 'size': m.get('size', 0)} for m in tags.json().get('models', [])]
        loaded: List[str] = []
        try:
            ps = requests.get(f'{base}/api/ps', timeout=timeout)
            if ps.ok:
                loaded = [m.get('name', '') for m in ps.json().get('models', [])]
        except Exception:
            pass  # /api/ps is best-effort; older Ollama builds may not expose it.
        return {'up': True, 'base': base, 'models': sorted(models, key=lambda m: m['name']), 'loaded': loaded}
    except Exception as e:
        return {'up': False, 'base': base, 'models': [], 'loaded': [], 'error': str(e)}

def discover_ollama_url(current: str='', timeout: float=1.5) -> Optional[str]:
    """Probe the usual places an Ollama server lives and return the first reachable
    /api/generate URL, or None. Order: explicit OLLAMA_URL env, the currently
    configured value, the Docker service name, then localhost. Adapted from ForgeOS's
    discovery chain, trimmed to the hosts that matter for a local workbench."""
    candidates = []
    for u in (os.getenv('OLLAMA_URL', ''), current,
              'http://ollama:11434', 'http://host.docker.internal:11434',
              'http://127.0.0.1:11434', 'http://localhost:11434'):
        base = ollama_base_url(u) if u else ''
        if base and base not in candidates:
            candidates.append(base)
    for base in candidates:
        try:
            if requests.get(f'{base}/api/tags', timeout=timeout).ok:
                return f'{base}/api/generate'
        except Exception:
            continue
    return None

def transform_to_vas(doc: SourceDoc, c: Classification, target_type: str, model: Optional[str]=None, url='http://localhost:11434/api/generate', context_text: str='') -> SourceDoc:
    target_labels={'rewrite_into_sop':'SOP','rewrite_into_runbook':'runbook','rewrite_into_customer_guide':'customer guide','rewrite_into_support_template':'support reply template','rewrite_into_policy':'policy','rewrite_into_training':'training document','rewrite_into_moderation_playbook':'moderation playbook','rewrite_into_admin_guide':'game/community admin guide','rewrite_into_lesson_plan':'moderator/admin lesson plan','rewrite_into_youtube_script':'YouTube training script','rewrite_into_linkedin_post':'LinkedIn educational post','rewrite_into_twitch_outline':'Twitch stream segment outline','rewrite_into_discord_staff_guide':'Discord staff guide','rewrite_into_community_announcement':'community announcement'}
    target=target_labels.get(target_type,'VainAsherStudios document')
    prompt=f'''Return JSON with keys title, summary, markdown, assumptions.
Create an original VainAsherStudios {target} from the source below.
Rules:
- Do not copy source wording or competitor/employer-specific phrasing.
- Extract principles, workflow shape, risks, checks, and useful operational patterns.
- Adapt for VainAsherStudios: website hosting, website development, managed IT, business email setup, AI workflow services, and gaming community operations.
- When relevant, support Minecraft, Project Zomboid, Rust, Discord, Twitch, YouTube, and LinkedIn outputs.
- For moderation/admin training outputs, focus on calm evidence-led moderation, proportional enforcement, escalation paths, safeguarding boundaries, and clear staff communication.
- Remove source company names, prices, claims, platform-specific policies unless required as assumptions.
- Mark assumptions clearly.
- Write in a calm, practical, professional VainAsherStudios voice.
- Treat the VainAsherStudios context as higher authority than the imported source.
- Use VAS context for brand voice, service catalogue, tools, IaC, privacy rules, and operational assumptions.
- If the source conflicts with VAS context, follow VAS context and list the conflict as an assumption/review note.

VAINASHERSTUDIOS_CONTEXT:
{context_text[:16000] if context_text else 'No additional VAS context pack supplied.'}

SOURCE_ORG: {c.source_org}
SOURCE_TITLE: {doc.title}
TARGET_TYPE: {target}
SOURCE_CONTENT:\n{doc.content[:14000]}'''
    data = ollama_json(prompt, model, url) if model else None
    if data and data.get('markdown'):
        title=data.get('title') or f'VAS Draft - {doc.title}'
        summary=data.get('summary') or f'Original VainAsherStudios {target} draft generated from reference material.'
        assumptions=normalise_assumptions(data.get('assumptions'))
        md=data['markdown'].strip()
        if assumptions:
            md += '\n\n## Assumptions for Review\n' + ''.join(f'\n- {a}' for a in assumptions)
        return SourceDoc(title=title, content=md, source='vainasherstudios_transform', source_id='', source_url='', raw_metadata={'transformed_from':doc.source_id,'source_org':c.source_org,'target_type':target_type,'summary':summary})
    # safe deterministic fallback
    title=f'VAS Draft - {doc.title}'
    md=f'''# {title}

> Draft generated for human review. This is an original VainAsherStudios working draft based on extracted operational patterns, not a republished source document.

## Purpose

Create a VainAsherStudios {target} for the relevant audience: clients, moderators, admins, community members, or content viewers. VAS covers website hosting, website development, managed IT, business email, AI workflows, and gaming community operations/training.

## VainAsherStudios Context Used

No AI model/context-aware rewrite was supplied for this fallback draft. Before approval, add relevant VAS context such as brand voice, service catalogue, IaC patterns, supported tools, privacy rules, and client support boundaries.

## Extracted Operational Pattern

- Identify the client-facing symptom or request.
- Confirm the affected service, account, domain, mailbox, website, workflow, or hosting environment.
- Gather safe diagnostic information without requesting unnecessary personal data.
- Check recent changes, configuration drift, credentials/access boundaries, DNS, SSL, backups, logs, and service health where relevant.
- Explain progress to the client in plain English.
- Escalate or schedule deeper work when the issue requires privileged access, destructive changes, or wider business impact.

## VainAsherStudios Procedure

1. Confirm the client, service, and urgency.
2. Check whether this is hosting, website, email, managed IT, or automation related.
3. Review the relevant internal runbook before acting.
4. Capture only the minimum information required.
5. Preserve client data and avoid destructive action unless approved.
6. Make the safest reversible change first.
7. Document actions, results, and next steps.
8. Send a clear client update.
9. Convert any new learning into an approved SOP update.

## Reusable Communication Template

Hi there,

Thanks for raising this. I’m checking the affected service or community situation and will work through the safest checks first. I’ll keep the investigation focused on the issue you reported and avoid making disruptive changes unless they are needed and approved.

I’ll update you with what I find, what I’ve changed, and any recommended next steps.

## Review Notes

- Source organisation: {c.source_org}
- Source role: {c.source_role}
- Reuse policy: {c.reuse_policy}
- Original source should remain reference-only.
- Human reviewer must adapt service-specific steps before approval.
'''
    return SourceDoc(title=title, content=md, source='vainasherstudios_transform', raw_metadata={'transformed_from':doc.source_id,'source_org':c.source_org,'target_type':target_type})

def merge_ai_classification(base: Classification, ai: Optional[Dict[str,Any]], taxonomy: Dict[str,List[str]]) -> Classification:
    if not ai: return base
    def valid(v,k,f): v=str(v or f); return v if v in taxonomy.get(k,[]) else f
    for attr,key in [('doc_type','doc_types'),('service','services'),('domain','domains'),('audience','audiences'),('authority','authorities'),('risk_level','risk_levels'),('source_org','source_orgs'),('source_role','source_roles'),('reuse_policy','reuse_policies'),('adaptation_action','adaptation_actions'),('rewrite_status','rewrite_statuses')]: setattr(base,attr,valid(ai.get(attr),key,getattr(base,attr)))
    for attr in ['summary','system','canonical_target','transform_notes']: setattr(base,attr,str(ai.get(attr) or getattr(base,attr)))
    base.customer_safe=bool(ai.get('customer_safe',base.customer_safe)); base.canonical=bool(ai.get('canonical',base.canonical))
    try: base.confidence=float(ai.get('confidence',base.confidence))
    except Exception: pass
    for t in ai.get('tags',[]):
        s=slugify(str(t));
        if s and s not in base.tags: base.tags.append(s)
    for r in ai.get('reasons',[]):
        if str(r) not in base.reasons: base.reasons.append(str(r))
    source_governance(base)
    if base.adaptation_action != 'reference_only': base.canonical_target=suggest_canonical_target(base)
    return base

def build_wiki_path(c: Classification) -> str:
    if c.source == 'vainasherstudios_transform': return c.canonical_target or suggest_canonical_target(c)
    if c.canonical and c.source_org == 'vainasherstudios': return c.canonical_target or suggest_canonical_target(c)
    return f'imports/{c.source_org}/{slugify(c.title)}'

def render_frontmatter(c: Classification)->str:
    data=dataclasses.asdict(c); data['path']=build_wiki_path(c); data['tags']=sorted(set(slugify(t) for t in c.tags if t)); return '---\n'+yaml.safe_dump(data,sort_keys=False,allow_unicode=True).strip()+'\n---\n\n'

def enriched_markdown(c: Classification, content: str)->str:
    body=clean_markdown(content)
    if not body.startswith('# '): body=f'# {c.title}\n\n{body}'
    return render_frontmatter(c)+body.strip()+'\n'

def publish_to_wikijs(wikijs_url: str, token: str, c: Classification, content: str)->Tuple[bool,str]:
    headers={'Authorization':f'Bearer {token}','Content-Type':'application/json'}
    vars={'content':clean_markdown(content).strip(),'description':c.summary or c.description,'editor':'markdown','isPublished':c.review_status!='rejected','locale':'en','path':build_wiki_path(c),'tags':sorted(set(slugify(t) for t in c.tags if t)),'title':c.title}
    try:
        r=requests.post(wikijs_url,headers=headers,json={'query':WIKIJS_CREATE_MUTATION,'variables':vars},timeout=30)
        if r.status_code!=200: return False, f'Wiki.js HTTP {r.status_code}: {r.text[:300]}'
        rr=r.json().get('data',{}).get('pages',{}).get('create',{}).get('responseResult',{})
        return (True,f"Published to /{vars['path']}") if rr.get('succeeded') else (False,rr.get('message','Wiki.js rejected the page'))
    except Exception as e: return False,str(e)
