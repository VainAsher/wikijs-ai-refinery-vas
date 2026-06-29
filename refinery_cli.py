#!/usr/bin/env python3
from __future__ import annotations
import argparse, os
from pathlib import Path
from refinery.connectors import CONNECTORS
from refinery.core import build_wiki_path, clean_markdown, deterministic_classify, enriched_markdown, load_taxonomy, publish_to_wikijs, transform_to_vas
from refinery.db import Store, import_key_for

def cfg(args):
    return {'local_markdown':{'path':args.input or args.local_path,'source_label':args.source_label or 'local_markdown'},'zendesk':{'url':args.zendesk_url or os.getenv('ZENDESK_URL','')},'mediawiki':{'api_url':args.mediawiki_api_url or os.getenv('MEDIAWIKI_API_URL',''),'cookie':args.mediawiki_cookie or os.getenv('MEDIAWIKI_COOKIE','')},'clickup':{'token':args.clickup_token or os.getenv('CLICKUP_TOKEN',''),'workspace_id':args.clickup_workspace_id or os.getenv('CLICKUP_WORKSPACE_ID','')},'gdocs':{'folder_id':args.gdocs_folder_id or os.getenv('GOOGLE_DRIVE_FOLDER_ID',''),'credentials_json':args.gdocs_credentials_json}}[args.connector]

def main():
    p=argparse.ArgumentParser(); sub=p.add_subparsers(dest='cmd',required=True)
    imp=sub.add_parser('import'); imp.add_argument('--connector',choices=sorted(CONNECTORS),required=True); imp.add_argument('--db',default='data/refinery.sqlite3'); imp.add_argument('--taxonomy',default='taxonomy.yml'); imp.add_argument('--limit',type=int,default=0); imp.add_argument('--input',default=''); imp.add_argument('--local-path',default=''); imp.add_argument('--source-label',default=''); imp.add_argument('--zendesk-url',default=''); imp.add_argument('--mediawiki-api-url',default=''); imp.add_argument('--mediawiki-cookie',default=''); imp.add_argument('--clickup-token',default=''); imp.add_argument('--clickup-workspace-id',default=''); imp.add_argument('--gdocs-folder-id',default=''); imp.add_argument('--gdocs-credentials-json',default='credentials.json')
    exp=sub.add_parser('export'); exp.add_argument('--db',default='data/refinery.sqlite3'); exp.add_argument('--output',default='data/export'); exp.add_argument('--status',default='reviewed')
    pub=sub.add_parser('publish'); pub.add_argument('--db',default='data/refinery.sqlite3'); pub.add_argument('--status',default='reviewed'); pub.add_argument('--wikijs-url',default=os.getenv('WIKIJS_URL','')); pub.add_argument('--wikijs-token',default=os.getenv('WIKIJS_TOKEN',''))
    args=p.parse_args()
    if args.cmd=='import':
        tax=load_taxonomy(args.taxonomy if Path(args.taxonomy).exists() else None); store=Store(args.db); count=0; new=0
        for doc in CONNECTORS[args.connector](cfg(args)).fetch(args.limit):
            doc.content=clean_markdown(doc.content); c=deterministic_classify(doc,tax)
            before=store.count_docs(); did=store.add_doc(doc,c,build_wiki_path(c),import_key=import_key_for(doc)); after=store.count_docs()
            tag='queued' if after>before else 'updated/skipped'
            new+=1 if after>before else 0
            print(f'{tag} #{did}: {doc.title} [{c.source_org}/{c.reuse_policy}/{c.service}] -> {build_wiki_path(c)}'); count+=1
        print(f'Processed {count} docs ({new} new) into {args.db}')
    elif args.cmd=='export':
        store=Store(args.db); out=Path(args.output); count=0
        for row in store.list_docs(status=args.status,limit=100000):
            c=store.classification(row); path=out/f'{build_wiki_path(c)}.md'; path.parent.mkdir(parents=True,exist_ok=True); path.write_text(enriched_markdown(c,row['content']),encoding='utf-8'); count+=1
        print(f'Exported {count} docs to {out}')
    elif args.cmd=='publish':
        if not args.wikijs_url or not args.wikijs_token: raise SystemExit('Missing Wiki.js URL/token')
        store=Store(args.db)
        for row in store.list_docs(status=args.status,limit=100000):
            c=store.classification(row); ok,msg=publish_to_wikijs(args.wikijs_url,args.wikijs_token,c,row['content']); store.update_doc(row['id'],c,build_wiki_path(c),published=ok,publish_message=msg); print(f"{row['id']} {c.title}: {msg}")
if __name__=='__main__': main()
