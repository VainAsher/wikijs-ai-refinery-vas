from __future__ import annotations
import datetime as dt, os
from pathlib import Path
from typing import Optional, List
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, PlainTextResponse
from fastapi.templating import Jinja2Templates
import time
from refinery.connectors import CONNECTORS
from refinery.core import SourceDoc, build_wiki_path, clean_markdown, deterministic_classify, enriched_markdown, load_taxonomy, merge_ai_classification, ollama_json, ollama_status, publish_to_wikijs, slugify, suggest_canonical_target, transform_to_vas
from refinery.db import Store, import_key_for, DocNotFound
from refinery.jobs import JOBS
from refinery.settings import Settings

BASE=Path(__file__).resolve().parent
DATA=Path(os.getenv('REFINERY_DATA','./data')); DATA.mkdir(parents=True,exist_ok=True)
DB_PATH=DATA/'refinery.sqlite3'
STORE=Store(str(DB_PATH))
SETTINGS=Settings(DATA/'settings.json')
TAXONOMY=load_taxonomy('taxonomy.yml' if Path('taxonomy.yml').exists() else None)
CONTEXT_DIR=DATA/'vas_context'; CONTEXT_DIR.mkdir(parents=True,exist_ok=True)
app=FastAPI(title='Wiki.js AI Refinery - VAS Community Ops')
templates=Jinja2Templates(directory=str(BASE/'templates'))

@app.exception_handler(DocNotFound)
async def _doc_not_found(request: Request, exc: DocNotFound):
    doc_id = exc.args[0] if exc.args else '?'
    # A stale link or a deleted/never-created id should be a clean 404, not a 500.
    html = (
        "<!doctype html><meta charset='utf-8'><title>Not found</title>"
        "<div style='font-family:system-ui,sans-serif;max-width:640px;margin:4rem auto;padding:0 1rem'>"
        f"<h1 style='margin-bottom:.25rem'>Document #{doc_id} not found</h1>"
        "<p style='color:#666'>It may have been deleted, deduplicated, or the link is stale.</p>"
        "<p><a href='/'>&larr; Back to the review queue</a></p></div>"
    )
    return HTMLResponse(html, status_code=404)


def safe_context_slug(name: str) -> str:
    return slugify(name or 'context-pack')


def ensure_default_contexts() -> None:
    defaults = {
        'brand_voice.md': """# VainAsherStudios Brand Voice

- Calm, practical, discreet, privacy-conscious, and human-first.
- Explain technical work in plain English without sounding patronising.
- Be honest about uncertainty, risk, assumptions, and next steps.
- Prefer stewardship, reliability, and long-term client trust over hype.
- Avoid copying third-party wording; use source docs only as reference material.
""",
        'service_catalogue.md': """# VainAsherStudios Service Catalogue

Core services:

- Website hosting and care plans
- Website development, especially WordPress/Elementor style SME sites
- Managed IT support for small UK businesses
- Business email setup and deliverability support, including DNS, SPF, DKIM, and DMARC
- AI workflow and automation setup, including n8n-style operational workflows
- Documentation, SOPs, maintenance reports, and client handover packs
- Gaming community operations, moderator/admin training, and game-server community support
""",
        'privacy_and_data_rules.md': """# Privacy and Data Rules

- Collect and retain the minimum client/community data needed to do the job.
- Treat credentials, tokens, API keys, private IPs, mailbox data, evidence packs, and player/member records as sensitive.
- Prefer reversible changes and explicit approval before destructive action.
- Do not expose internal notes or reference-source material in customer/community-facing content.
- Customer-facing and community-facing drafts must be rewritten in VainAsherStudios language and reviewed before publication.
""",
        'technical_stack_iac.md': """# Technical Stack and IaC Context

Common VAS/self-hosted stack references may include:

- Traefik / Cloudflare / DNS / SSL routing
- Docker Compose and service-level runbooks
- Nextcloud, Invoice Ninja, Mailcow, Authentik, Wiki.js, Zammad, Paperless-ngx, Vaultwarden
- Proxmox and backup/restore procedures
- Infrastructure documentation should distinguish declared IaC truth from human operational SOPs.
""",
        'gaming_community_ops.md': """# Gaming Community Operations

VAS supports and trains moderation/admin teams for gaming communities including Minecraft, Project Zomboid, Rust, and Discord-based communities.

Principles:

- Evidence-led moderation: act from logs, screenshots, reports, context, and clear rules.
- Proportional enforcement: warning, mute, kick, temp ban, permanent ban, appeal route where appropriate.
- Staff safety: moderators should not be left alone with high-conflict situations.
- Clear escalation: serious safeguarding, harassment, threats, doxxing, fraud, chargebacks, or platform-risk issues escalate.
- Community trust: explain outcomes where appropriate without exposing private evidence or staff notes.
""",
        'moderator_training_standards.md': """# Moderator and Admin Training Standards

Training materials should be practical, scenario-based, and easy for volunteer staff to use.

Every module should include:

- Learning objective
- When this applies
- Step-by-step decision flow
- What evidence to capture
- What not to do
- Example staff wording
- Escalation threshold
- Reflection / quiz prompts
""",
        'content_channels_strategy.md': """# VAS Content Channels Strategy

VAS content channels may include YouTube, LinkedIn, Twitch, and Discord.

- YouTube: structured training, walkthroughs, practical scenarios, and long-form educational content.
- LinkedIn: professional lessons from community ops, managed IT, hosting, AI workflows, and moderation leadership.
- Twitch: live build/moderation/admin training sessions, Q&A, demos, and behind-the-scenes operations.
- Discord: community announcements, staff guidance, micro-training, polls, and operational coordination.

Content should teach without leaking private community, client, employer, or competitor details.
""",
        'platform_minecraft_project_zomboid_rust.md': """# Platform Context: Minecraft, Project Zomboid, Rust

Minecraft:
- Common issues: griefing, claims, mod/plugin conflicts, permissions, staff abuse concerns, server performance, rollback requests.

Project Zomboid:
- Common issues: PvE/PvP boundaries, safehouse disputes, loot respawn rules, admin spawning accusations, RP conflict.

Rust:
- Common issues: toxicity, cheating accusations, raid disputes, wipe cycles, clan conflict, chat moderation, admin transparency.

Always adapt guidance to the community's published rules and evidence standards.
""",
    }
    for filename, content in defaults.items():
        path = CONTEXT_DIR / filename
        if not path.exists():
            path.write_text(content, encoding='utf-8')


def list_context_packs():
    ensure_default_contexts()
    packs=[]
    for path in sorted(CONTEXT_DIR.glob('*.md')):
        packs.append({'slug':path.stem,'filename':path.name,'title':path.stem.replace('_',' ').replace('-',' ').title(),'content':path.read_text(encoding='utf-8',errors='replace')})
    return packs


def read_context_packs(names: List[str], extra: str='') -> str:
    ensure_default_contexts()
    chunks=[]
    wanted={safe_context_slug(n) for n in names if n}
    for path in sorted(CONTEXT_DIR.glob('*.md')):
        if path.stem in wanted:
            chunks.append(f'\n\n--- VAS CONTEXT PACK: {path.stem} ---\n' + path.read_text(encoding='utf-8',errors='replace'))
    if extra.strip():
        chunks.append('\n\n--- AD HOC CONTEXT PROVIDED FOR THIS TRANSFORM ---\n' + extra.strip())
    return '\n'.join(chunks).strip()


def row_view(r):
    c=STORE.classification(r); return {'row':r,'c':c,'path':build_wiki_path(c)}


def classify_and_store(doc: SourceDoc, ollama_model: str = '') -> int:
    doc.content=clean_markdown(doc.content)
    c=deterministic_classify(doc,TAXONOMY)
    if ollama_model:
        prompt=("Return JSON classification for this doc. Include source_org, source_role, reuse_policy, "
                "adaptation_action, rewrite_status, canonical_target, domain, service, doc_type, audience. "
                f"TITLE:{doc.title}\nCONTENT:{doc.content[:12000]}")
        c=merge_ai_classification(c,ollama_json(prompt,ollama_model,SETTINGS.get('ollama_url')),TAXONOMY)
    return STORE.add_doc(doc,c,build_wiki_path(c),import_key=import_key_for(doc))


def parse_source_dir_lines(source_dirs: str) -> List[tuple]:
    """Parse the /bulk textarea into (label, path) pairs. Each line may be
    'label|path', 'label=path', or a bare path (label defaults to the dir name)."""
    pairs=[]
    for line in source_dirs.splitlines():
        line=line.strip()
        if not line or line.startswith('#'): continue
        if '|' in line: label,path=line.split('|',1)
        elif '=' in line: label,path=line.split('=',1)
        else: label,path=Path(line).name,line
        pairs.append((label.strip(), path.strip().strip('"')))
    return pairs


def count_markdown(pairs: List[tuple], limit: int) -> Optional[int]:
    """Best-effort total for the progress bar: count .md files across the source
    dirs (respecting a per-dir limit). Returns None if nothing is countable, which
    makes the tray show an indeterminate bar rather than a wrong percentage."""
    total=0
    for _label,path in pairs:
        p=Path(path)
        if not p.exists(): continue
        n=sum(1 for _ in p.rglob('*.md'))
        total += min(n,limit) if limit else n
    return total or None


@app.get('/',response_class=HTMLResponse)
def index(request:Request,status:Optional[str]=None,source:Optional[str]=None,q:Optional[str]=None,source_org:Optional[str]=None,service:Optional[str]=None,doc_type:Optional[str]=None,rewrite_status:Optional[str]=None,authority:Optional[str]=None,page:int=1,page_size:int=50):
    page=max(page,1); page_size=max(10,min(page_size,250)); offset=(page-1)*page_size
    rows=STORE.list_docs(status,source,q,page_size,offset,source_org,service,doc_type,rewrite_status,authority)
    total=STORE.count_docs(status,source,q,source_org,service,doc_type,rewrite_status,authority)
    qs={'status':status or '','source':source or '','q':q or '','source_org':source_org or '','service':service or '','doc_type':doc_type or '','rewrite_status':rewrite_status or '','authority':authority or '','page_size':page_size}
    return templates.TemplateResponse(request, 'index.html', {'docs':[row_view(r) for r in rows],'counts':STORE.counts(),'taxonomy':TAXONOMY,'filters':qs,'page':page,'page_size':page_size,'total':total,'pages':max(1,(total+page_size-1)//page_size)})


@app.get('/connectors',response_class=HTMLResponse)
def connectors_page(request:Request):
    return templates.TemplateResponse(request, 'connectors.html', {'connectors':sorted(CONNECTORS)})


@app.post('/connectors/run')
def connectors_run(connector:str=Form(...),limit:int=Form(25),local_path:str=Form(''),zendesk_url:str=Form(''),mediawiki_api_url:str=Form(''),mediawiki_cookie:str=Form(''),clickup_token:str=Form(''),clickup_workspace_id:str=Form(''),gdocs_folder_id:str=Form(''),gdocs_credentials_json:str=Form('credentials.json'),source_label:str=Form(''),ollama_model:str=Form('')):
    cfgs={'local_markdown':{'path':local_path,'source_label':source_label or 'local_markdown'},'zendesk':{'url':zendesk_url or os.getenv('ZENDESK_URL','')},'mediawiki':{'api_url':mediawiki_api_url or os.getenv('MEDIAWIKI_API_URL',''),'cookie':mediawiki_cookie or os.getenv('MEDIAWIKI_COOKIE','')},'clickup':{'token':clickup_token or os.getenv('CLICKUP_TOKEN',''),'workspace_id':clickup_workspace_id or os.getenv('CLICKUP_WORKSPACE_ID','')},'gdocs':{'folder_id':gdocs_folder_id or os.getenv('GOOGLE_DRIVE_FOLDER_ID',''),'credentials_json':gdocs_credentials_json}}
    con=CONNECTORS[connector](cfgs[connector])
    dest=f'/?status=needs_review&q=imported'
    def work(job):
        imported=0
        for doc in con.fetch(limit=limit):
            classify_and_store(doc, ollama_model); imported+=1
            job.advance(1, f'{imported} imported — {doc.title[:60]}')
        job.finish(f'Imported {imported} document(s) from {connector}', href=dest)
    JOBS.run('connector', f'Importing from {connector}', work, total=limit or None, href=dest)
    return RedirectResponse(dest,status_code=303)


@app.get('/bulk', response_class=HTMLResponse)
def bulk_page(request: Request):
    return templates.TemplateResponse(request, 'bulk.html', {'taxonomy': TAXONOMY})


@app.post('/bulk/import-source-dirs')
def bulk_import_source_dirs(source_dirs:str=Form(...),limit:int=Form(0),ollama_model:str=Form('')):
    """Import many local source directories. Lines support: source_label|path or source_label=path."""
    pairs=parse_source_dir_lines(source_dirs)
    total=count_markdown(pairs, limit)
    dest=f'/?q=&page_size=100&status=needs_review'
    def work(job):
        imported=0
        for label,path in pairs:
            con=CONNECTORS['local_markdown']({'path':path, 'source_label':label})
            for doc in con.fetch(limit=limit if limit else 0):
                classify_and_store(doc, ollama_model); imported+=1
                job.advance(1, f'{imported} imported — {doc.title[:60]}')
        job.finish(f'Imported {imported} document(s) from {len(pairs)} source(s)', href=dest)
    label=f'Importing markdown from {len(pairs)} source(s)' if pairs else 'Importing markdown'
    JOBS.run('import', label, work, total=total, href=dest)
    return RedirectResponse(dest, status_code=303)


@app.post('/bulk/apply')
def bulk_apply(status:Optional[str]=Form(None),source_org:Optional[str]=Form(None),service:Optional[str]=Form(None),doc_type:Optional[str]=Form(None),rewrite_status:Optional[str]=Form(None),q:Optional[str]=Form(None),set_adaptation_action:str=Form(''),set_rewrite_status:str=Form(''),set_review_status:str=Form(''),add_tag:str=Form(''),limit:int=Form(500)):
    ids=STORE.selected_ids(status=status or None,q=q or None,source_org=source_org or None,service=service or None,doc_type=doc_type or None,rewrite_status=rewrite_status or None,limit=limit)
    dest='/?page_size=100'
    def work(job):
        updated=0
        for doc_id in ids:
            row=STORE.get_doc(doc_id); c=STORE.classification(row)
            if set_adaptation_action: c.adaptation_action=set_adaptation_action
            if set_rewrite_status: c.rewrite_status=set_rewrite_status
            if set_review_status: c.review_status=set_review_status
            if add_tag:
                tag=slugify(add_tag)
                if tag and tag not in c.tags: c.tags.append(tag)
            if c.adaptation_action and c.adaptation_action not in ['none','reference_only'] and not c.canonical_target:
                c.canonical_target=suggest_canonical_target(c)
            STORE.update_doc(doc_id,c,build_wiki_path(c)); updated+=1
            job.advance(1, f'{updated}/{len(ids)} updated')
        job.finish(f'Updated {updated} document(s)', href=dest)
    JOBS.run('bulk', f'Applying changes to {len(ids)} document(s)', work, total=len(ids) or None, href=dest)
    return RedirectResponse(dest, status_code=303)


@app.get('/docs/{doc_id}/edit')
def edit_alias(doc_id:int):
    return RedirectResponse(f'/docs/{doc_id}', status_code=303)


@app.get('/docs/{doc_id}',response_class=HTMLResponse)
def review_doc(request:Request,doc_id:int):
    row=STORE.get_doc(doc_id); c=STORE.classification(row)
    return templates.TemplateResponse(request, 'review.html', {'row':row,'c':c,'taxonomy':TAXONOMY,'wiki_path':build_wiki_path(c),'content':row['content'],'context_packs':list_context_packs()})


@app.post('/docs/{doc_id}/save')
def save_doc(doc_id:int,title:str=Form(...),summary:str=Form(''),content:str=Form(...),doc_type:str=Form('unknown'),service:str=Form('unknown'),domain:str=Form('vain_asher_studios'),system:str=Form('unknown'),audience:str=Form('unknown'),authority:str=Form('imported_unreviewed'),risk_level:str=Form('medium'),contains_pii:str=Form('unknown'),contains_secrets:str=Form('unknown'),customer_safe:Optional[str]=Form(None),canonical:Optional[str]=Form(None),review_status:str=Form('needs_review'),reviewed_by:str=Form(''),tags:str=Form(''),source_org:str=Form('unknown'),source_role:str=Form('imported_source'),reuse_policy:str=Form('rewrite_required'),adaptation_action:str=Form('reference_only'),canonical_target:str=Form(''),rewrite_status:str=Form('needs_rewrite'),transform_notes:str=Form('')):
    row=STORE.get_doc(doc_id); c=STORE.classification(row)
    for k,v in {'title':title,'summary':summary,'doc_type':doc_type,'service':service,'domain':domain,'system':system,'audience':audience,'authority':authority,'risk_level':risk_level,'contains_pii':contains_pii,'contains_secrets':contains_secrets,'review_status':review_status,'reviewed_by':reviewed_by,'source_org':source_org,'source_role':source_role,'reuse_policy':reuse_policy,'adaptation_action':adaptation_action,'canonical_target':canonical_target,'rewrite_status':rewrite_status,'transform_notes':transform_notes}.items(): setattr(c,k,v)
    c.customer_safe=customer_safe=='true'; c.canonical=canonical=='true'
    if review_status=='reviewed' and not c.last_reviewed: c.last_reviewed=dt.date.today().isoformat()
    c.tags=sorted(set(slugify(t.strip()) for t in tags.split(',') if t.strip()))
    if not c.canonical_target and c.adaptation_action!='reference_only': c.canonical_target=suggest_canonical_target(c)
    STORE.update_doc(doc_id,c,build_wiki_path(c),content=content)
    return RedirectResponse(f'/docs/{doc_id}',status_code=303)


@app.post('/docs/{doc_id}/quick')
def quick(doc_id:int,action:str=Form(...),reviewed_by:str=Form('')):
    row=STORE.get_doc(doc_id); c=STORE.classification(row)
    if action=='approve': c.review_status='reviewed'; c.authority='approved' if c.authority=='imported_unreviewed' else c.authority; c.reviewed_by=reviewed_by or c.reviewed_by; c.last_reviewed=dt.date.today().isoformat()
    elif action=='reject': c.review_status='rejected'; c.authority='archived'; c.rewrite_status='rejected'
    elif action=='canonical': c.canonical=True; c.review_status='reviewed'; c.authority='canonical'; c.rewrite_status='approved'; c.reviewed_by=reviewed_by or c.reviewed_by; c.last_reviewed=dt.date.today().isoformat()
    STORE.update_doc(doc_id,c,build_wiki_path(c)); return RedirectResponse('/',status_code=303)


@app.post('/docs/{doc_id}/transform')
def transform_doc(doc_id:int,target_action:str=Form('rewrite_into_sop'),ollama_model:str=Form(''),context_pack:List[str]=Form([]),extra_context:str=Form('')):
    row=STORE.get_doc(doc_id); c=STORE.classification(row); source=SourceDoc(title=row['title'],content=row['content'],source=row['source'],source_id=str(row['id']),source_url=row['source_url'] or '',raw_metadata={'row_id':row['id']})
    context_text=read_context_packs(context_pack, extra_context)
    draft=transform_to_vas(source,c,target_action,ollama_model or SETTINGS.get('ollama_model') or None,SETTINGS.get('ollama_url'),context_text=context_text)
    dc=deterministic_classify(draft,TAXONOMY); dc.source_org='vainasherstudios'; dc.source_role='owned'; dc.reuse_policy='owned_original'; dc.adaptation_action=target_action; dc.rewrite_status='draft_generated'; dc.review_status='needs_review'; dc.authority='draft'; dc.canonical=False; dc.customer_safe=False; dc.transform_source_doc_id=str(doc_id); dc.canonical_target=suggest_canonical_target(dc); dc.tags=sorted(set(dc.tags+['vas-transform','draft-generated']))
    new_id=STORE.add_doc(draft,dc,build_wiki_path(dc))
    c.adaptation_action=target_action; c.rewrite_status='draft_generated'; c.canonical_target=dc.canonical_target; c.transform_notes=f'Draft created as document #{new_id}'
    STORE.update_doc(doc_id,c,build_wiki_path(c))
    return RedirectResponse(f'/docs/{new_id}',status_code=303)


@app.post('/docs/{doc_id}/publish')
def publish_doc(doc_id:int,wikijs_url:str=Form(''),wikijs_token:str=Form('')):
    row=STORE.get_doc(doc_id); c=STORE.classification(row); url=wikijs_url or SETTINGS.get('wikijs_url'); token=wikijs_token or SETTINGS.get('wikijs_token')
    if not url or not token: STORE.update_doc(doc_id,c,build_wiki_path(c),publish_message='Missing WIKIJS_URL or WIKIJS_TOKEN'); return RedirectResponse(f'/docs/{doc_id}',status_code=303)
    ok,msg=publish_to_wikijs(url,token,c,row['content']); STORE.update_doc(doc_id,c,build_wiki_path(c),published=ok,publish_message=msg); return RedirectResponse(f'/docs/{doc_id}',status_code=303)


@app.get('/docs/{doc_id}/markdown',response_class=PlainTextResponse)
def md(doc_id:int):
    row=STORE.get_doc(doc_id); return enriched_markdown(STORE.classification(row),row['content'])


@app.get('/context',response_class=HTMLResponse)
def context_page(request:Request, pack:Optional[str]=None):
    packs=list_context_packs(); selected=None
    if pack:
        for item in packs:
            if safe_context_slug(item['slug'])==safe_context_slug(pack): selected=item
    return templates.TemplateResponse(request, 'context.html', {'packs':packs,'selected':selected})


@app.post('/context/save')
def context_save(name:str=Form(...),content:str=Form(...)):
    ensure_default_contexts(); slug=safe_context_slug(name); (CONTEXT_DIR/f'{slug}.md').write_text(content,encoding='utf-8'); return RedirectResponse(f'/context?pack={slug}',status_code=303)


@app.post('/context/delete')
def context_delete(name:str=Form(...)):
    path=CONTEXT_DIR/f'{safe_context_slug(name)}.md'
    if path.exists(): path.unlink()
    return RedirectResponse('/context',status_code=303)


@app.get('/export')
def export(status:str='reviewed'):
    out=DATA/'export'; out.mkdir(parents=True,exist_ok=True); count=0
    for row in STORE.list_docs(status=status,limit=100000):
        c=STORE.classification(row); path=out/f'{build_wiki_path(c)}.md'; path.parent.mkdir(parents=True,exist_ok=True); path.write_text(enriched_markdown(c,row['content']),encoding='utf-8'); count+=1
    return {'exported':count,'folder':str(out)}


@app.get('/jobs/active')
def jobs_active():
    """Progress feed polled by the tray in base.html. Returns running jobs plus any
    that finished in the last few seconds (so 'Done'/'Failed' is briefly visible)."""
    return {'jobs': JOBS.visible()}


@app.get('/guide',response_class=HTMLResponse)
def guide_page(request:Request):
    return templates.TemplateResponse(request, 'guide.html', {})


@app.get('/config',response_class=HTMLResponse)
def config_page(request:Request, notice:Optional[str]=None):
    oll=ollama_status(SETTINGS.get('ollama_url'))
    return templates.TemplateResponse(request, 'config.html', {'settings':SETTINGS.view(),'ollama':oll,'notice':notice})


@app.post('/config/save')
def config_save(ollama_url:str=Form(''),ollama_model:str=Form(''),wikijs_url:str=Form(''),wikijs_token:str=Form('')):
    SETTINGS.save({'ollama_url':ollama_url,'ollama_model':ollama_model,'wikijs_url':wikijs_url,'wikijs_token':wikijs_token})
    return RedirectResponse('/config?notice=Settings+saved',status_code=303)


@app.post('/config/test-ollama')
def config_test_ollama(model:str=Form('')):
    """Run a tiny generation against the chosen model and report latency + length, so
    the operator can gauge real quality/speed before committing to a model."""
    model=model or SETTINGS.get('ollama_model')
    if not model:
        return RedirectResponse('/config?notice=No+model+selected',status_code=303)
    t0=time.time()
    data=ollama_json('Return JSON {"markdown":"<one short sentence about calm, evidence-led moderation>"}',model,SETTINGS.get('ollama_url'),timeout=60)
    dt=time.time()-t0
    if data and data.get('markdown'):
        words=len(str(data['markdown']).split()); wps=words/dt if dt else 0
        msg=f'{model}: OK in {dt:.1f}s ({words} words, ~{wps:.1f} w/s)'
    else:
        msg=f'{model}: no response in {dt:.1f}s (model missing or Ollama down)'
    return RedirectResponse(f'/config?notice={msg.replace(" ","+")}',status_code=303)


@app.get('/monitor',response_class=HTMLResponse)
def monitor_page(request:Request):
    counts=STORE.counts()
    breakdowns={f:STORE.breakdown(f) for f in ('source_org','service','doc_type','rewrite_status','authority')}
    db_bytes=DB_PATH.stat().st_size if DB_PATH.exists() else 0
    oll=ollama_status(SETTINGS.get('ollama_url'))
    return templates.TemplateResponse(request, 'monitor.html', {
        'counts':counts,'breakdowns':breakdowns,'ollama':oll,
        'db_path':str(DB_PATH),'db_mb':round(db_bytes/1048576,2),
        'wikijs_set':bool(SETTINGS.get('wikijs_url') and SETTINGS.get('wikijs_token')),
    })
