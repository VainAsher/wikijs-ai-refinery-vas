from __future__ import annotations
import dataclasses, json, sqlite3, datetime as dt, hashlib, threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from refinery.core import Classification, SourceDoc, reference_source_orgs


def import_key_for(doc: SourceDoc) -> Optional[str]:
    """Stable identity for an imported doc, used to make re-imports idempotent.
    Returns None when there's no source_id to key on (then no dedup is applied)."""
    if not doc.source_id:
        return None
    return hashlib.sha1(f'{doc.source}::{doc.source_id}'.encode('utf-8')).hexdigest()


class DocNotFound(KeyError):
    """Raised when a doc id isn't in the store. Subclasses KeyError so any existing
    `except KeyError` still works, but lets the web layer return a clean 404."""


# Classification fields that are denormalised into real, indexed columns so the
# review-queue filters can use exact equality + an index instead of a fragile
# `classification_json LIKE '%"field": "value"%'` substring scan. Keeping this list
# in one place means add_doc/update_doc/migrate/_where all stay in sync.
DENORM_FIELDS = ('source_org', 'service', 'doc_type', 'rewrite_status', 'authority')

SCHEMA='''
CREATE TABLE IF NOT EXISTS docs (
 id INTEGER PRIMARY KEY AUTOINCREMENT,title TEXT NOT NULL,source TEXT NOT NULL,source_id TEXT,source_url TEXT,original_updated_at TEXT,content TEXT NOT NULL,raw_metadata_json TEXT NOT NULL DEFAULT '{}',classification_json TEXT NOT NULL,review_status TEXT NOT NULL DEFAULT 'needs_review',wiki_path TEXT,published INTEGER NOT NULL DEFAULT 0,publish_message TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_docs_review_status ON docs(review_status);
CREATE INDEX IF NOT EXISTS idx_docs_source ON docs(source);
CREATE INDEX IF NOT EXISTS idx_docs_title ON docs(title);
CREATE INDEX IF NOT EXISTS idx_docs_updated ON docs(updated_at);
'''


def _denorm(c: Classification) -> Dict[str, str]:
    """Pull the indexed/filterable fields off a classification."""
    return {f: str(getattr(c, f, '') or '') for f in DENORM_FIELDS}


class Store:
    def __init__(self,path='refinery.sqlite3'):
        self.path=Path(path); self.path.parent.mkdir(parents=True,exist_ok=True); self.conn=sqlite3.connect(self.path,check_same_thread=False); self.conn.row_factory=sqlite3.Row; self.conn.executescript(SCHEMA); self.conn.commit()
        self._lock=threading.Lock()  # serialises writes from the shared connection (bulk import + a click can race)
        self._migrate()
    def _migrate(self)->None:
        """Idempotent, additive migration. Adds import_key (dedup) and the denormalised
        filter columns without touching unrelated data, then backfills the new columns
        from existing classification_json so old DBs gain working indexed filters."""
        cols={r['name'] for r in self.conn.execute('PRAGMA table_info(docs)')}
        if 'import_key' not in cols:
            self.conn.execute('ALTER TABLE docs ADD COLUMN import_key TEXT')
        # Partial unique index: enforces uniqueness for imports but allows many
        # NULLs (transformed drafts and source_id-less docs are never deduped).
        self.conn.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_docs_import_key ON docs(import_key) WHERE import_key IS NOT NULL')

        added=[f for f in DENORM_FIELDS if f not in cols]
        for f in added:
            self.conn.execute(f'ALTER TABLE docs ADD COLUMN {f} TEXT')
        for f in DENORM_FIELDS:
            self.conn.execute(f'CREATE INDEX IF NOT EXISTS idx_docs_{f} ON docs({f})')
        self.conn.commit()
        if added:
            self._backfill_denorm(added)

    def _backfill_denorm(self, fields: List[str]) -> None:
        """Populate freshly-added denorm columns from classification_json for rows that
        predate them. Runs once (only for columns we just added)."""
        rows=self.conn.execute('SELECT id, classification_json FROM docs').fetchall()
        with self._lock:
            for r in rows:
                try: data=json.loads(r['classification_json'])
                except Exception: data={}
                sets=', '.join(f'{f}=?' for f in fields)
                params=[str(data.get(f,'') or '') for f in fields]+[r['id']]
                self.conn.execute(f'UPDATE docs SET {sets} WHERE id=?', params)
            self.conn.commit()

    def add_doc(self,doc:SourceDoc,c:Classification,wiki_path:str,import_key:Optional[str]=None)->int:
        now=dt.datetime.now(dt.timezone.utc).isoformat(); d=_denorm(c)
        with self._lock:
            if import_key:
                existing=self.conn.execute('SELECT id, review_status FROM docs WHERE import_key=?',(import_key,)).fetchone()
                if existing:
                    # Re-import of a doc we've already seen. Refresh content only if it's
                    # still untouched; never overwrite started review/transform work.
                    if existing['review_status']=='needs_review':
                        sets=', '.join(f'{f}=?' for f in DENORM_FIELDS)
                        self.conn.execute(f'UPDATE docs SET title=?, content=?, classification_json=?, wiki_path=?, {sets}, updated_at=? WHERE id=?',
                            [doc.title,doc.content,json.dumps(dataclasses.asdict(c),ensure_ascii=False),wiki_path]+[d[f] for f in DENORM_FIELDS]+[now,existing['id']]); self.conn.commit()
                    return int(existing['id'])
            cols='title,source,source_id,source_url,original_updated_at,content,raw_metadata_json,classification_json,review_status,wiki_path,import_key,'+','.join(DENORM_FIELDS)+',created_at,updated_at'
            placeholders=','.join('?'*(11+len(DENORM_FIELDS)+2))
            params=[doc.title,doc.source,doc.source_id,doc.source_url,doc.original_updated_at,doc.content,json.dumps(doc.raw_metadata,ensure_ascii=False),json.dumps(dataclasses.asdict(c),ensure_ascii=False),c.review_status,wiki_path,import_key]+[d[f] for f in DENORM_FIELDS]+[now,now]
            cur=self.conn.execute(f'INSERT INTO docs ({cols}) VALUES ({placeholders})',params); self.conn.commit(); return int(cur.lastrowid)
    def _where(self,status=None,source=None,q=None,source_org=None,service=None,doc_type=None,rewrite_status=None,authority=None)->Tuple[str,List[Any]]:
        clauses=[]; params=[]
        # All exact-match filters now hit real indexed columns rather than scanning the
        # classification_json blob with LIKE (faster, and immune to values that contain
        # JSON punctuation or LIKE wildcards).
        for col,val in [('review_status',status),('source',source),('source_org',source_org),('service',service),('doc_type',doc_type),('rewrite_status',rewrite_status),('authority',authority)]:
            if val: clauses.append(f'{col}=?'); params.append(val)
        if q:
            # Free-text search still scans content; escape LIKE wildcards so a user's
            # literal % or _ doesn't silently widen the match.
            esc=q.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')
            clauses.append("(title LIKE ? ESCAPE '\\' OR content LIKE ? ESCAPE '\\')"); params += [f'%{esc}%',f'%{esc}%']
        where='WHERE '+' AND '.join(clauses) if clauses else ''
        return where, params
    def list_docs(self,status:Optional[str]=None,source:Optional[str]=None,q:Optional[str]=None,limit:int=100,offset:int=0,source_org:Optional[str]=None,service:Optional[str]=None,doc_type:Optional[str]=None,rewrite_status:Optional[str]=None,authority:Optional[str]=None)->List[sqlite3.Row]:
        where,params=self._where(status,source,q,source_org,service,doc_type,rewrite_status,authority)
        return list(self.conn.execute(f'SELECT * FROM docs {where} ORDER BY updated_at DESC LIMIT ? OFFSET ?',params+[limit,offset]))
    def count_docs(self,status:Optional[str]=None,source:Optional[str]=None,q:Optional[str]=None,source_org:Optional[str]=None,service:Optional[str]=None,doc_type:Optional[str]=None,rewrite_status:Optional[str]=None,authority:Optional[str]=None)->int:
        where,params=self._where(status,source,q,source_org,service,doc_type,rewrite_status,authority)
        return int(self.conn.execute(f'SELECT COUNT(*) n FROM docs {where}',params).fetchone()['n'])
    def get_doc(self,doc_id:int)->sqlite3.Row:
        row=self.conn.execute('SELECT * FROM docs WHERE id=?',(doc_id,)).fetchone()
        if not row: raise DocNotFound(doc_id)
        return row
    def classification(self,row:sqlite3.Row)->Classification:
        data=json.loads(row['classification_json']); allowed={f.name for f in dataclasses.fields(Classification)}; data={k:v for k,v in data.items() if k in allowed}; return Classification(**data)
    def update_doc(self,doc_id:int,c:Classification,wiki_path:str,content:Optional[str]=None,published:Optional[bool]=None,publish_message:Optional[str]=None)->None:
        row=self.get_doc(doc_id); now=dt.datetime.now(dt.timezone.utc).isoformat(); new_content=content if content is not None else row['content']; new_pub=int(published) if published is not None else row['published']; new_msg=publish_message if publish_message is not None else row['publish_message']; d=_denorm(c)
        with self._lock:
            sets=', '.join(f'{f}=?' for f in DENORM_FIELDS)
            self.conn.execute(f'UPDATE docs SET title=?, content=?,classification_json=?,review_status=?,wiki_path=?,published=?,publish_message=?,{sets},updated_at=? WHERE id=?',[c.title,new_content,json.dumps(dataclasses.asdict(c),ensure_ascii=False),c.review_status,wiki_path,new_pub,new_msg]+[d[f] for f in DENORM_FIELDS]+[now,doc_id]); self.conn.commit()
    def selected_ids(self,status:Optional[str]=None,source:Optional[str]=None,q:Optional[str]=None,source_org:Optional[str]=None,service:Optional[str]=None,doc_type:Optional[str]=None,rewrite_status:Optional[str]=None,authority:Optional[str]=None,limit:int=5000)->List[int]:
        where,params=self._where(status,source,q,source_org,service,doc_type,rewrite_status,authority)
        return [int(r['id']) for r in self.conn.execute(f'SELECT id FROM docs {where} ORDER BY updated_at DESC LIMIT ?',params+[limit]).fetchall()]
    def counts(self)->Dict[str,int]:
        rows=self.conn.execute('SELECT review_status,COUNT(*) n FROM docs GROUP BY review_status').fetchall(); out={r['review_status']:int(r['n']) for r in rows}; out['total']=int(self.conn.execute('SELECT COUNT(*) n FROM docs').fetchone()['n']); out['published']=int(self.conn.execute('SELECT COUNT(*) n FROM docs WHERE published=1').fetchone()['n'])
        # Counters now group on the indexed columns in one pass per field.
        for field, values in {'source_org':reference_source_orgs()+['vainasherstudios'], 'rewrite_status':['needs_rewrite','draft_generated','approved']}.items():
            grouped={r[field]:int(r['n']) for r in self.conn.execute(f'SELECT {field},COUNT(*) n FROM docs GROUP BY {field}').fetchall()}
            for value in values:
                out[f'{field}:{value}']=grouped.get(value,0)
        return out
    def breakdown(self, field: str, limit: int = 30) -> List[Tuple[str, int]]:
        """Counts grouped by one indexed field, biggest first — used by the monitoring
        dashboard. Whitelisted to indexed columns to keep the f-string injection-safe."""
        if field not in DENORM_FIELDS + ('review_status', 'source'):
            raise ValueError(f'not a groupable field: {field}')
        rows=self.conn.execute(f"SELECT {field} k, COUNT(*) n FROM docs GROUP BY {field} ORDER BY n DESC LIMIT ?", (limit,)).fetchall()
        return [(r['k'] or '(none)', int(r['n'])) for r in rows]
