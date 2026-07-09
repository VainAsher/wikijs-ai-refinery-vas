from __future__ import annotations
import dataclasses, datetime as dt, json, os, re
from typing import Any, Dict, List, Optional, Tuple
import requests, yaml

# Instance identity (D13/D15): a second stamped instance (e.g. the training
# refinery) must be de-brandable without a fork - UI labels, generated draft
# titles, and generation prompts all derive from these. Defaults preserve
# the original VAS identity exactly.
ORG_TAG = os.getenv('REFINERY_ORG_TAG', 'VAS')
ORG_NAME = os.getenv('REFINERY_ORG_NAME', 'VainAsherStudios')
ORG_LINE = os.getenv('REFINERY_ORG_LINE', 'VainAsherStudios services (hosting, web development, managed IT, business email, AI workflows, gaming community ops) and reference the VAS managed stack/tools from the context where relevant')

DEFAULT_TAXONOMY = {
 'doc_types':['sop','runbook','policy','how_to','troubleshooting','faq','customer_template','internal_note','architecture','iac_reference','service_overview','incident_report','postmortem','checklist','training','glossary','decision_record','draft','moderation_playbook','training_module','lesson_plan','content_script','social_post_template','community_announcement','incident_response','admin_guide','stream_outline','discord_staff_guide','bisectbot_mission','ticketlab_scenario','quiz','unknown'],
 'audiences':['public','customer','internal','admin_only','private','community_member','moderator','admin','trainee','content_audience','unknown'],
 'authorities':['canonical','approved','imported_unreviewed','draft','deprecated','conflicting','archived','unknown'],
 'risk_levels':['low','medium','high','critical'],
 'review_statuses':['needs_review','reviewed','rejected'],
 'services':['website_hosting','website_development','managed_it','business_email','ai_workflows','automation','wordpress','nextcloud','invoice_ninja','mailcow','authentik','traefik','cloudflare','proxmox','backup','monitoring','billing','pterodactyl','minecraft','project_zomboid','rust','discord','twitch','youtube','linkedin','canvas','gaming_community_management','moderator_training','admin_training','game_server_hosting','unknown'],
 'domains':['vain_asher_studios','client','community','personal','household','wedding','employer_hosting','game_dev','managed_it','web_hosting','web_development','ai_workflows','gaming_community_ops','moderator_training','content_creation','game_server_hosting','unknown'],
 'source_orgs':['vainasherstudios','employer_hosting','competitor_hosting_1','competitor_hosting_2','infrastructure_provider_1','infrastructure_provider_2','authentik','pterodactyl','rust','canvas','traefik','mailcow','nextcloud','proxmox','cloudflare','invoice_ninja','wikijs','zammad','vaultwarden','paperless','forgejo','documenso','coolify','n8n','client','internal','community_reference','unknown'],
 'source_roles':['canonical','owned','reference_only','evidence','imported_source','competitor_reference','employer_reference','infrastructure_reference','vendor_documentation','community_reference','training_reference','unknown'],
 'reuse_policies':['owned_original','rewrite_required','reference_only','quote_prohibited','review_required','forbidden','owned_training_material','unknown'],
 'adaptation_actions':['none','reference_only','rewrite_into_sop','rewrite_into_runbook','rewrite_into_customer_guide','rewrite_into_support_template','rewrite_into_policy','rewrite_into_training','rewrite_into_moderation_playbook','rewrite_into_admin_guide','rewrite_into_lesson_plan','rewrite_into_youtube_script','rewrite_into_linkedin_post','rewrite_into_twitch_outline','rewrite_into_discord_staff_guide','rewrite_into_community_announcement','rewrite_into_bisectbot_mission','rewrite_into_ticketlab_scenario','rewrite_into_quiz','gap_analysis_only','reject_archive'],
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
    brand_score: int = -1   # 0-100 brand-compliance score; -1 = not scored yet
    reasons: List[str] = dataclasses.field(default_factory=list)
    # VainAsherStudios refinery upgrade
    business_owner: str = ORG_NAME
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


@dataclasses.dataclass
class Finding:
    """One detected secret/PII span. Backs the redaction gate (adapted from
    CrucibleOS's Scrubber): a human reviews these and redacts before publishing."""
    kind: str
    severity: str   # critical | high | medium | low
    match: str
    start: int
    end: int

    @property
    def placeholder(self) -> str:
        return f'[REDACTED:{self.kind}]'

    @property
    def preview(self) -> str:
        """Partially-masked snippet so the gate is reviewable without fully re-exposing
        the secret in the table."""
        s = self.match
        if len(s) <= 8:
            return (s[0] + '***' + s[-1]) if len(s) > 2 else '***'
        return s[:3] + '…' + s[-3:]


# (kind, severity, pattern). Order matters: earlier/critical patterns win on overlap.
_SCRUB_PATTERNS: List[Tuple[str, str, str]] = [
    ('private_key', 'critical', r'-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----[\s\S]*?-----END (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----'),
    ('aws_access_key', 'critical', r'\b(?:AKIA|ASIA)[0-9A-Z]{16}\b'),
    ('aws_secret_key', 'critical', r'(?i)aws_secret_access_key\s*[:=]\s*[\'"]?([A-Za-z0-9/+]{40})[\'"]?'),
    ('gcp_api_key', 'critical', r'\bAIza[0-9A-Za-z\-_]{35}\b'),
    ('slack_token', 'critical', r'\bxox[baprs]-[0-9A-Za-z-]{10,}\b'),
    ('github_token', 'critical', r'\bgh[pousr]_[A-Za-z0-9]{20,}\b'),
    ('jwt', 'high', r'\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b'),
    ('bearer_token', 'high', r'(?i)\bbearer\s+[A-Za-z0-9._\-]{16,}'),
    ('password_assignment', 'high', r'(?i)\b(?:password|passwd|pwd|secret|api[_-]?key|token)\b\s*[:=]\s*[\'"]?([^\s\'"]{6,})'),
    ('public_ipv4', 'medium', r'\b(?!(?:10|127)\.)(?!192\.168\.)(?!172\.(?:1[6-9]|2\d|3[01])\.)(?:\d{1,3}\.){3}\d{1,3}\b'),
    ('email', 'medium', r'\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b'),
    ('private_ipv4', 'low', r'\b(?:10\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01])|192\.168)\.\d{1,3}\.\d{1,3}\b'),
    ('mac_address', 'low', r'\b(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}\b'),
]
_SCRUB_COMPILED = [(k, s, re.compile(p)) for k, s, p in _SCRUB_PATTERNS]


def scrub_findings(text: str) -> List[Finding]:
    """Find all secret/PII spans, then drop overlaps keeping the earliest/longest
    (so an email inside a longer credential line isn't double-reported)."""
    raw: List[Finding] = []
    for kind, sev, pat in _SCRUB_COMPILED:
        for m in pat.finditer(text or ''):
            raw.append(Finding(kind=kind, severity=sev, match=m.group(0), start=m.start(), end=m.end()))
    raw.sort(key=lambda f: (f.start, -(f.end - f.start)))
    pruned: List[Finding] = []
    last_end = -1
    for f in raw:
        if f.start >= last_end:
            pruned.append(f); last_end = f.end
    return pruned


def apply_redactions(text: str, findings: List[Finding]) -> str:
    """Replace each finding's exact match with its placeholder. Literal replacement is
    order-independent and immune to offset drift, so selecting a subset is safe."""
    for f in findings:
        text = text.replace(f.match, f.placeholder)
    return text

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
        c.reasons.append('Upstream tool documentation: adapt into owned runbooks/SOPs, do not republish verbatim, and check the upstream licence.')
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
    action_map={'rewrite_into_sop':'sops','rewrite_into_runbook':'runbooks','rewrite_into_policy':'policies','rewrite_into_customer_guide':'guides','rewrite_into_support_template':'templates/support-replies','rewrite_into_training':'training','rewrite_into_moderation_playbook':'community/moderation-playbooks','rewrite_into_admin_guide':'community/admin-guides','rewrite_into_lesson_plan':'training/lesson-plans','rewrite_into_youtube_script':'content/youtube','rewrite_into_linkedin_post':'content/linkedin','rewrite_into_twitch_outline':'content/twitch','rewrite_into_discord_staff_guide':'community/discord-staff-guides','rewrite_into_community_announcement':'community/announcements','rewrite_into_bisectbot_mission':'training/bisectbot-missions','rewrite_into_ticketlab_scenario':'training/ticketlab-scenarios','rewrite_into_quiz':'training/quizzes'}
    base=action_map.get(c.adaptation_action,'reference')
    if base in ['policies','reference','training/bisectbot-missions','training/ticketlab-scenarios','training/quizzes']: return f'{base}/{slug}'
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

# Ollama's default context window is small (2048 on many builds), which silently
# truncates our long context+source prompts from the front — dropping the VAS context.
# And forcing format=json makes models emit a tiny markdown value. So we (a) always set
# a generous num_ctx, and (b) generate the transform as PLAIN text, not JSON.
OLLAMA_NUM_CTX = int(os.getenv('OLLAMA_NUM_CTX', '8192'))         # prompt + output token budget
OLLAMA_NUM_PREDICT = int(os.getenv('OLLAMA_NUM_PREDICT', '4096')) # max tokens for a generated draft

def ollama_json(prompt: str, model: str, url='http://localhost:11434/api/generate', timeout: int = 180, options: Optional[Dict[str,Any]]=None) -> Optional[Dict[str,Any]]:
    """Structured (JSON-mode) generation for classification/extraction. Sets num_ctx so
    the whole prompt is actually read instead of being truncated to the model default."""
    try:
        body={'model':model,'prompt':prompt,'stream':False,'format':'json','options':options or {'num_ctx':OLLAMA_NUM_CTX}}
        r=requests.post(url,json=body,timeout=timeout); r.raise_for_status(); return json.loads(r.json().get('response','{}'))
    except Exception: return None

def ollama_text(prompt: str, model: str, url='http://localhost:11434/api/generate', timeout: int = 300, options: Optional[Dict[str,Any]]=None) -> Optional[str]:
    """Plain-text generation for long-form drafts. Avoids JSON mode (which makes models
    under-generate) and gives a large num_ctx + num_predict so output is detailed."""
    try:
        body={'model':model,'prompt':prompt,'stream':False,'options':options or {'num_ctx':OLLAMA_NUM_CTX,'num_predict':OLLAMA_NUM_PREDICT}}
        r=requests.post(url,json=body,timeout=timeout); r.raise_for_status(); return (r.json().get('response') or '').strip()
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
    configured value, any OLLAMA_LAN_HOSTS (for homelab/LAN Ollama), the Docker host
    gateway, the Docker service name, then localhost. Adapted from ForgeOS's discovery
    chain. OLLAMA_LAN_HOSTS is a comma-separated list of host or host:port entries."""
    lan = []
    for h in os.getenv('OLLAMA_LAN_HOSTS', '').split(','):
        h = h.strip()
        if h:
            lan.append(h if h.startswith(('http://', 'https://')) else f'http://{h}{"" if ":" in h else ":11434"}')
    candidates = []
    for u in ([os.getenv('OLLAMA_URL', ''), current] + lan +
              ['http://host.docker.internal:11434', 'http://ollama:11434',
               'http://127.0.0.1:11434', 'http://localhost:11434']):
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

# ---------------------------------------------------------------------------
# Variation dials  (adapted from ForgeOS): tune voice/length/structure per run
# ---------------------------------------------------------------------------
DIALS_DEFAULTS: Dict[str, Any] = {
    'tone': 'professional',            # professional | conversational | authoritative | playful | neutral
    'audience': 'intermediate',        # beginner | intermediate | expert
    'length_bias': 'standard',         # concise | standard | comprehensive
    'citation_strictness': 'standard', # loose | standard | strict
    'reading_grade': '',               # '' or a US grade level 3-16
    'emoji_policy': 'none',            # none | sparing
    'include_cta': True,
}
DIAL_OPTIONS: Dict[str, List[str]] = {
    'tone': ['professional', 'conversational', 'authoritative', 'playful', 'neutral'],
    'audience': ['beginner', 'intermediate', 'expert'],
    'length_bias': ['concise', 'standard', 'comprehensive'],
    'citation_strictness': ['loose', 'standard', 'strict'],
    'emoji_policy': ['none', 'sparing'],
}

def normalise_dials(raw: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Merge submitted dials over defaults, ignoring blanks/invalid options so a partial
    form (or none) is always safe. Precedence: submitted value > built-in default."""
    d = dict(DIALS_DEFAULTS)
    if raw:
        for k in DIALS_DEFAULTS:
            v = raw.get(k)
            if v in (None, ''):
                continue
            if k in DIAL_OPTIONS and str(v) not in DIAL_OPTIONS[k]:
                continue
            d[k] = v
    cta = d['include_cta']
    d['include_cta'] = cta if isinstance(cta, bool) else str(cta).lower() in ('1', 'true', 'yes', 'on')
    return d

def dials_directives(d: Dict[str, Any]) -> str:
    """Render dials as an instruction block injected into the transform prompt."""
    length_map = {'concise': 'Be concise — trim to the essentials (~30% shorter).',
                  'standard': 'Use a standard length appropriate to the document type.',
                  'comprehensive': 'Be comprehensive and thorough (~35% longer) without padding.'}
    cite_map = {'loose': 'Cite sources only where it clearly helps.',
                'standard': 'Cite key claims and reference the source where relevant.',
                'strict': 'Cite every factual claim; flag anything unsupported as an assumption.'}
    lines = [
        f"- Tone: {d['tone']}.",
        f"- Pitch the writing for a {d['audience']} audience.",
        f"- {length_map.get(d['length_bias'], '')}",
        f"- {cite_map.get(d['citation_strictness'], '')}",
        f"- Emoji policy: {d['emoji_policy']}.",
        "- End with a clear call to action." if d['include_cta'] else "- Do not add a call to action.",
    ]
    if str(d.get('reading_grade') or '').strip():
        lines.append(f"- Aim for roughly US reading grade {d['reading_grade']}.")
    return '\n'.join(l for l in lines if l.strip('- ').strip())


# ---------------------------------------------------------------------------
# Brand profile + compliance scoring  (adapted from ForgeOS brand_scorer)
# ---------------------------------------------------------------------------
DEFAULT_BRAND: Dict[str, Any] = {
    'name': ORG_NAME,
    'tone_guide': ('Noir, technical, human, honest — hope beneath the cynicism. Clarity first for '
                   'operational docs (SOPs, runbooks, customer guides); full brand voice for community, '
                   'content, and creative work.'),
    'core_values': ['Technical depth over hype', 'Honesty about risk and uncertainty',
                    'Communities are built, not harvested', 'Leave systems better than we found them'],
    'personality_traits': ['Direct and honest', 'Calm and practical', 'Teacher-like, patient',
                           'Dry humour', 'Willing to admit uncertainty'],
    'avoid_language': ['clickbait', 'game-changer', 'game changer', 'synergy', 'revolutionary',
                       'cutting-edge', 'best-in-class', 'industry-leading', 'obviously', 'effortless',
                       'unleash', 'supercharge'],
}

def brand_violations(text: str, brand: Dict[str, Any]) -> List[str]:
    """Avoided words/phrases that actually appear in the text (whole-word, case-insensitive)."""
    low = (text or '').lower()
    found = []
    for term in (brand.get('avoid_language') or []):
        t = str(term).lower().strip()
        if t and re.search(rf'(?<![\w-]){re.escape(t)}(?![\w-])', low):
            found.append(t)
    return sorted(set(found))

def brand_compliance(text: str, brand: Dict[str, Any], model: Optional[str]=None,
                     url='http://localhost:11434/api/generate') -> Dict[str, Any]:
    """Score text 0-100 against the brand profile. With a model it asks the LLM for a
    nuanced read (tone match + violations); without one it falls back to a deterministic
    penalty for each avoided-language hit. Always returns a dict, never raises."""
    violations = brand_violations(text, brand)
    if model:
        prompt = (
            'Return JSON {"overall_score": 0-100, "tone_match": 0-1, "notes": "<one short sentence>"}.\n'
            'Score how well the TEXT matches this brand.\n'
            f'BRAND_NAME: {brand.get("name","")}\n'
            f'TONE_GUIDE: {brand.get("tone_guide","")}\n'
            f'AVOID_LANGUAGE: {", ".join(brand.get("avoid_language", []))}\n'
            f'TEXT:\n{(text or "")[:8000]}'
        )
        data = ollama_json(prompt, model, url, timeout=90)
        if data and isinstance(data.get('overall_score'), (int, float)):
            return {'overall_score': int(max(0, min(100, data['overall_score']))),
                    'tone_match': data.get('tone_match'),
                    'language_violations': violations,
                    'notes': str(data.get('notes', ''))[:300], 'method': 'llm'}
    score = max(0, 100 - len(violations) * 8)
    return {'overall_score': score, 'tone_match': None, 'language_violations': violations,
            'notes': 'Deterministic check (no model): score = 100 − 8×avoided-language hits.',
            'method': 'deterministic'}

_FACT_STOPWORDS = set(('this that with from your have will been they them then than into over more most some '
                       'such only also able when where which what their there here about would could should '
                       'using used make made does done need needs the and for are not you can use any all').split())

def extract_facts(doc: SourceDoc, model: Optional[str]=None, url='http://localhost:11434/api/generate') -> Dict[str, List[str]]:
    """Pull candidate keywords + factual claims for the fact-verification gate (the
    ForgeOS compliance-gate idea). Uses the LLM when a model is supplied, otherwise a
    deterministic pass over headings, lead sentences, and frequent terms."""
    content = doc.content or ''
    if model:
        data = ollama_json(
            'Return JSON {"keywords": ["..."], "facts": ["..."]}. Extract up to 8 short keywords and '
            'up to 8 concise, checkable factual claims from the document. Facts must be self-contained.\n'
            f'TITLE: {doc.title}\nCONTENT:\n{content[:8000]}', model, url, timeout=90)
        if data:
            facts = [str(x).strip() for x in (data.get('facts') or []) if str(x).strip()][:8]
            kws = [str(x).strip() for x in (data.get('keywords') or []) if str(x).strip()][:8]
            if facts or kws:
                return {'keywords': kws, 'facts': facts}
    # deterministic fallback
    lines = [l.strip() for l in content.splitlines() if l.strip()]
    headings = [re.sub(r'^#+\s*', '', l) for l in lines if l.startswith('#')]
    body = re.sub(r'^#+.*$', '', content, flags=re.M)
    sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+', body) if 30 <= len(s.strip()) <= 200]
    facts = (headings + sentences)[:8]
    freq: Dict[str, int] = {}
    for w in re.findall(r'[a-zA-Z][a-zA-Z0-9_-]{3,}', content.lower()):
        if w not in _FACT_STOPWORDS:
            freq[w] = freq.get(w, 0) + 1
    kws = [w for w, _ in sorted(freq.items(), key=lambda x: -x[1])[:8]]
    return {'keywords': kws, 'facts': facts}

def derive_content_gaps(coverage: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Turn per-service coverage counts into prioritised content-gap suggestions
    (adapted from ForgeOS's gap analyzer, simplified to what the store can answer):
      - rewrite_backlog: reference docs exist but no owned draft (highest value)
      - no_coverage:     a service with zero docs (worth creating)
      - shallow:         1-2 docs only (thin)."""
    gaps: List[Dict[str, Any]] = []
    for c in coverage:
        if c['owned'] == 0 and c['reference'] > 0:
            gaps.append({'service': c['service'], 'kind': 'rewrite_backlog', 'priority': 3,
                         'note': f"{c['reference']} reference doc(s) but no owned draft — prime rewrite candidate."})
        elif c['total'] == 0:
            gaps.append({'service': c['service'], 'kind': 'no_coverage', 'priority': 2,
                         'note': 'No documents yet — candidate to create from scratch.'})
        elif c['total'] <= 2:
            gaps.append({'service': c['service'], 'kind': 'shallow', 'priority': 1,
                         'note': f"Only {c['total']} doc(s) — shallow coverage, worth deepening."})
    gaps.sort(key=lambda g: (-g['priority'], g['service']))
    return gaps

def load_brand(path) -> Dict[str, Any]:
    """Load the structured brand profile, seeding a default file on first use and
    merging it over DEFAULT_BRAND so a partial brand.yaml is always complete."""
    from pathlib import Path as _Path
    p = _Path(path)
    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(yaml.safe_dump(DEFAULT_BRAND, sort_keys=False, allow_unicode=True), encoding='utf-8')
    merged = dict(DEFAULT_BRAND)
    try:
        loaded = yaml.safe_load(p.read_text('utf-8')) or {}
        if isinstance(loaded, dict):
            merged.update(loaded)
    except Exception:
        pass
    return merged


def transform_to_vas(doc: SourceDoc, c: Classification, target_type: str, model: Optional[str]=None, url='http://localhost:11434/api/generate', context_text: str='', dials: Optional[Dict[str, Any]]=None) -> SourceDoc:
    target_labels={'rewrite_into_sop':'SOP','rewrite_into_runbook':'runbook','rewrite_into_customer_guide':'customer guide','rewrite_into_support_template':'support reply template','rewrite_into_policy':'policy','rewrite_into_training':'training document','rewrite_into_moderation_playbook':'moderation playbook','rewrite_into_admin_guide':'game/community admin guide','rewrite_into_lesson_plan':'moderator/admin lesson plan','rewrite_into_youtube_script':'YouTube training script','rewrite_into_linkedin_post':'LinkedIn educational post','rewrite_into_twitch_outline':'Twitch stream segment outline','rewrite_into_discord_staff_guide':'Discord staff guide','rewrite_into_community_announcement':'community announcement'}
    target=target_labels.get(target_type,f'{ORG_NAME} document')
    # Generate Markdown DIRECTLY (not via JSON mode, which crushes output length). The
    # key directive is repeated after the source so the model weights it on recency.
    prompt=f'''Write an original, detailed {ORG_NAME} {target} in Markdown, based on the SOURCE below.

Treat the ORG_CONTEXT as HIGHER AUTHORITY than the source. Rules:
- Do not copy source wording or competitor/employer-specific phrasing; extract the principles, workflow, risks, checks, and operational patterns.
- Adapt for {ORG_LINE}.
- For moderation/admin outputs: calm, evidence-led moderation, proportional enforcement, escalation paths, safeguarding, clear staff wording.
- Remove source company names, prices, and platform-specific policies unless needed as an assumption.
- Write in the {ORG_NAME} voice. Be thorough and well-structured: include a title, a short intro, prerequisites, a step-by-step procedure, verification/checks, risks, and escalation where appropriate.
- End with a "## Assumptions for Review" section listing anything you assumed or any source/context conflicts.

VARIATION DIRECTIVES (tune voice, length, and structure):
{dials_directives(normalise_dials(dials))}

ORG_CONTEXT (higher authority than the source):
{context_text[:7000] if context_text else 'No additional context pack supplied.'}

SOURCE_ORG: {c.source_org}
SOURCE_TITLE: {doc.title}
SOURCE_CONTENT:
{doc.content[:8000]}

Now write the complete Markdown {target}. Start with a single "# " title line, use the ORG_CONTEXT as higher authority, and be detailed.'''
    text = ollama_text(prompt, model, url) if model else None
    if text and len(text.strip()) >= 80:
        md=clean_markdown(text)
        # Title from the first H1 the model wrote, else a safe default.
        title=next((l[2:].strip() for l in md.splitlines() if l.startswith('# ')), f'{ORG_TAG} Draft - {doc.title}')
        # Summary from the first real paragraph (not a heading/bullet).
        summary=next((l.strip() for l in md.splitlines() if l.strip() and not l.lstrip().startswith(('#','-','*','>'))), f'Original {ORG_NAME} {target} draft.')[:300]
        if not md.lstrip().startswith('# '): md=f'# {title}\n\n{md}'
        return SourceDoc(title=title, content=md.strip(), source='vainasherstudios_transform', source_id='', source_url='', raw_metadata={'transformed_from':doc.source_id,'source_org':c.source_org,'target_type':target_type,'summary':summary})
    # safe deterministic fallback
    title=f'{ORG_TAG} Draft - {doc.title}'
    md=f'''# {title}

> Draft generated for human review. This is an original {ORG_NAME} working draft based on extracted operational patterns, not a republished source document.

## Purpose

Create a {ORG_NAME} {target} for the relevant audience: clients, staff, trainees, moderators, or community members.

## {ORG_NAME} Context Used

No AI model/context-aware rewrite was supplied for this fallback draft. Before approval, add relevant {ORG_TAG} context such as brand voice, service catalogue, IaC patterns, supported tools, privacy rules, and client support boundaries.

## Extracted Operational Pattern

- Identify the client-facing symptom or request.
- Confirm the affected service, account, domain, mailbox, website, workflow, or hosting environment.
- Gather safe diagnostic information without requesting unnecessary personal data.
- Check recent changes, configuration drift, credentials/access boundaries, DNS, SSL, backups, logs, and service health where relevant.
- Explain progress to the client in plain English.
- Escalate or schedule deeper work when the issue requires privileged access, destructive changes, or wider business impact.

## {ORG_NAME} Procedure

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

TRAINING_ARTIFACT_TARGETS = ('bisectbot_mission', 'ticketlab_scenario', 'quiz')

_TRAINING_TARGET_LABELS = {
    'bisectbot_mission': 'a BisectBot training mission pack',
    'ticketlab_scenario': 'a TicketLab support-simulation scenario',
    'quiz': 'a single multiple-choice quiz question',
}

_TRAINING_TARGET_SCHEMAS = {
    'bisectbot_mission': '''Return JSON with this exact shape:
{"schemaVersion":1,"contentType":"bisectbot.trainingMission",
 "mission":{"id":"<slug>","title":"<short ticket title>","customerReport":"<1-2 sentence customer-facing ticket description>"},
 "quizzes":[{"id":"<slug>_q1","type":"multiple_choice","title":"<short title>","question":"<a question testing understanding of the source content>","choices":["<4 options>"],"correctAnswers":[<index of correct option>],"explanation":"<why the correct answer is correct>"}]}
Include 3-5 quizzes if the source content supports it, each with a distinct question.''',
    'ticketlab_scenario': '''Return JSON with this exact shape (it will be converted to YAML):
{"schema_version":2,
 "metadata":{"id":"<slug>","title":"<short title>","version":"0.1.0","author":"refinery-draft","provenance":{"created":"<ISO date>","source":"internal"},"difficulty":<1-5>,"tags":["<tags>"],"estimated_minutes":<int>},
 "panel":{"adapter":"mock","min_version":"1.11"},
 "ticket":{"subject":"<subject>","priority":"low|medium|high","customer":{"name":"<name>","persona":"<short persona description>"},"body":"<realistic customer message describing the problem, do not name the cause>"},
 "environment":{"server":{"name":"<server name>","egg":"<game/service>","limits":{},"variables":{}}},
 "fault":{"steps":[{"action":"<one of: set_variable,set_startup_command,set_limits,write_file,delete_file,start_server,stop_server,wait>","value":"<optional>","key":"<optional>","seconds":<optional int>}]},
 "conversation":{"persona":"<same persona>","satisfaction_start":<0-100>,"hidden_facts":[{"id":"<slug>","fact":"<a fact the customer knows but won't volunteer>","reveal_keywords":["<keywords that reveal it>"]}]},
 "verification":{"solutions":[{"id":"<slug>","grade":"full","score":100,"label":"<short label>","assertions":[{"type":"server_state","operator":"equals","expected":"running"}],"feedback":"<why this is the right fix>"}]},
 "scoring":{"max_verify_attempts":5,"target_minutes":<int>},
 "teardown":{"policy":"on_pass_or_expiry","expiry_minutes":60}}
Base the fault and the fix on the actual troubleshooting steps described in the source content.''',
    'quiz': '''Return JSON with this exact shape:
{"questionType":"multiple_choice","prompt":"<a question testing understanding of the source content>","choices":["<4 options>"],"correctAnswers":[<index of correct option>],"explanation":"<why the correct answer is correct>"}''',
}


def _stub_bisectbot_mission(doc: SourceDoc) -> Dict[str, Any]:
    slug = slugify(doc.title)
    return {
        'schemaVersion': 1,
        'contentType': 'bisectbot.trainingMission',
        'mission': {
            'id': f'refinery_{slug}',
            'title': f'[NEEDS AUTHOR REVIEW] {doc.title}',
            'customerReport': f'Training simulation loaded: {doc.title}.',
        },
        'quizzes': [{
            'id': f'{slug}_q1',
            'type': 'multiple_choice',
            'title': '[NEEDS AUTHOR REVIEW]',
            'question': f'[NEEDS AUTHOR REVIEW] Write a real question sourced from: {doc.title}',
            'choices': ['[NEEDS AUTHOR REVIEW] option A', 'option B', 'option C', 'option D'],
            'correctAnswers': [0],
            'explanation': '[NEEDS AUTHOR REVIEW] explanation not yet written.',
        }],
    }


def _stub_ticketlab_scenario(doc: SourceDoc) -> Dict[str, Any]:
    slug = slugify(doc.title)
    return {
        'schema_version': 2,
        'metadata': {
            'id': slug,
            'title': f'[NEEDS AUTHOR REVIEW] {doc.title}',
            'version': '0.1.0',
            'author': 'refinery-draft',
            'provenance': {'created': dt.datetime.now(dt.timezone.utc).date().isoformat(), 'source': 'internal'},
            'difficulty': 2,
            'tags': ['needs-review'],
            'estimated_minutes': 10,
        },
        'panel': {'adapter': 'mock', 'min_version': '1.11'},
        'ticket': {
            'subject': f'[NEEDS AUTHOR REVIEW] {doc.title}',
            'priority': 'medium',
            'customer': {'name': 'Customer', 'persona': 'neutral'},
            'body': '[NEEDS AUTHOR REVIEW] Write a realistic customer message here.',
        },
        'environment': {'server': {'name': 'draft-server', 'egg': 'unknown', 'limits': {}, 'variables': {}}},
        'fault': {'steps': [{'action': 'wait', 'seconds': 1}]},
        'conversation': {'persona': 'neutral', 'satisfaction_start': 50, 'hidden_facts': []},
        'verification': {
            'solutions': [{
                'id': 'needs-review',
                'grade': 'full',
                'score': 100,
                'label': '[NEEDS AUTHOR REVIEW]',
                'assertions': [{'type': 'server_state', 'operator': 'equals', 'expected': 'running'}],
                'feedback': '[NEEDS AUTHOR REVIEW] feedback not yet written.',
            }],
        },
        'scoring': {'max_verify_attempts': 5, 'target_minutes': 10},
        'teardown': {'policy': 'on_pass_or_expiry', 'expiry_minutes': 60},
    }


def _stub_quiz(doc: SourceDoc) -> Dict[str, Any]:
    return {
        'questionType': 'multiple_choice',
        'prompt': f'[NEEDS AUTHOR REVIEW] Write a real question sourced from: {doc.title}',
        'choices': ['[NEEDS AUTHOR REVIEW] option A', 'option B', 'option C', 'option D'],
        'correctAnswers': [0],
        'explanation': '[NEEDS AUTHOR REVIEW] explanation not yet written.',
    }


_STUB_BUILDERS = {
    'bisectbot_mission': _stub_bisectbot_mission,
    'ticketlab_scenario': _stub_ticketlab_scenario,
    'quiz': _stub_quiz,
}

_TITLE_GETTERS = {
    'bisectbot_mission': lambda a, doc: a.get('mission', {}).get('title') or f'Mission: {doc.title}',
    'ticketlab_scenario': lambda a, doc: a.get('metadata', {}).get('title') or f'Scenario: {doc.title}',
    'quiz': lambda a, doc: f'Quiz: {doc.title}',
}


def _valid_quiz_shape(q: Dict[str, Any]) -> bool:
    """Shared by bisectbot_mission (per-quiz) and quiz (top-level) checks.
    Catches the real failure mode seen from live Ollama output: a
    syntactically fine correctAnswers list whose index is out of range for
    the choices actually returned (e.g. 4 choices asked for, model only gave
    3, but still pointed at index 3) - BisectBot's own validatePack() rejects
    this, so it must be caught here or the deterministic stub should be used
    instead."""
    choices = q.get('choices')
    correct = q.get('correctAnswers')
    if not (isinstance(choices, list) and len(choices) >= 2):
        return False
    if not (isinstance(correct, list) and len(correct) > 0):
        return False
    return all(isinstance(i, int) and 0 <= i < len(choices) for i in correct)


def validate_training_artifact(target_format: str, artifact: Dict[str, Any]) -> bool:
    """Plain shape check, not a full schema validation - deliberately not
    importing ticketlab's or BisectBot's schema types (separate products).
    Ollama's 'format':'json' constrains syntax, not our field shape, so this
    is what decides whether the AI draft is trustworthy or the deterministic
    stub is used instead."""
    try:
        if target_format == 'bisectbot_mission':
            mission = artifact.get('mission', {})
            quizzes = artifact.get('quizzes')
            return bool(mission.get('id')) and bool(mission.get('title')) and isinstance(quizzes, list) and len(quizzes) > 0 and all(
                q.get('question') and _valid_quiz_shape(q) for q in quizzes
            )
        if target_format == 'ticketlab_scenario':
            fault_steps = artifact.get('fault', {}).get('steps')
            solutions = artifact.get('verification', {}).get('solutions')
            return bool(artifact.get('metadata', {}).get('id')) and bool(artifact.get('ticket', {}).get('subject')) and isinstance(fault_steps, list) and len(fault_steps) > 0 and isinstance(solutions, list) and len(solutions) > 0
        if target_format == 'quiz':
            return bool(artifact.get('prompt')) and _valid_quiz_shape(artifact)
    except (AttributeError, TypeError):
        return False
    return False


def transform_to_training_artifact(doc: SourceDoc, c: Classification, target_format: str, model: Optional[str] = None, url='http://localhost:11434/api/generate') -> SourceDoc:
    if target_format not in _TRAINING_TARGET_SCHEMAS:
        raise ValueError(f'unknown training artifact target: {target_format}')

    artifact: Optional[Dict[str, Any]] = None
    if model:
        prompt = f'''Create {_TRAINING_TARGET_LABELS[target_format]} from the source content below.
{_TRAINING_TARGET_SCHEMAS[target_format]}
Do not copy the source wording verbatim - write an original question/scenario grounded in the source's facts.
SOURCE_TITLE: {doc.title}
SOURCE_CONTENT:
{doc.content[:14000]}'''
        candidate = ollama_json(prompt, model, url)
        if candidate and validate_training_artifact(target_format, candidate):
            artifact = candidate

    if artifact is None:
        artifact = _STUB_BUILDERS[target_format](doc)

    artifact_format = 'yaml' if target_format == 'ticketlab_scenario' else 'json'
    content = (
        yaml.safe_dump(artifact, sort_keys=False, allow_unicode=True)
        if artifact_format == 'yaml'
        else json.dumps(artifact, indent=2, ensure_ascii=False)
    )
    title = _TITLE_GETTERS[target_format](artifact, doc)

    return SourceDoc(
        title=title,
        content=content,
        source='vainasherstudios_transform',
        raw_metadata={
            'transformed_from': doc.source_id,
            'source_org': c.source_org,
            'target_type': target_format,
            'artifact_format': artifact_format,
        },
    )


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
    if c.source in ('vainasherstudios_transform', 'vainasherstudios_pipeline'): return c.canonical_target or suggest_canonical_target(c)
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
