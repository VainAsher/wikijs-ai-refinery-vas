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
CREATE TABLE IF NOT EXISTS runs (
 id INTEGER PRIMARY KEY AUTOINCREMENT,created_at TEXT NOT NULL,source_doc_id INTEGER,new_doc_id INTEGER,
 target_action TEXT,model TEXT,dials_json TEXT NOT NULL DEFAULT '{}',brand_score INTEGER NOT NULL DEFAULT -1,
 latency_ms INTEGER NOT NULL DEFAULT 0,used_model INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_runs_created ON runs(created_at);
CREATE TABLE IF NOT EXISTS pipeline_runs (
 id INTEGER PRIMARY KEY AUTOINCREMENT,pipeline_id TEXT NOT NULL,source_doc_ids_json TEXT NOT NULL DEFAULT '[]',
 target_action TEXT,service TEXT,audience TEXT,status TEXT NOT NULL DEFAULT 'running',new_doc_id INTEGER,
 state_json TEXT NOT NULL DEFAULT '{}',created_at TEXT NOT NULL,updated_at TEXT NOT NULL,completed_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_pipeline_runs_created ON pipeline_runs(created_at);
CREATE TABLE IF NOT EXISTS pass_runs (
 id INTEGER PRIMARY KEY AUTOINCREMENT,pipeline_run_id INTEGER NOT NULL,pass_id TEXT NOT NULL,status TEXT,
 mode TEXT,model TEXT,report_json TEXT NOT NULL DEFAULT '{}',latency_ms INTEGER NOT NULL DEFAULT 0,created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_pass_runs_pipeline ON pass_runs(pipeline_run_id);
CREATE TABLE IF NOT EXISTS doc_lineage (
 id INTEGER PRIMARY KEY AUTOINCREMENT,parent_doc_id INTEGER,child_doc_id INTEGER,relationship TEXT,
 pipeline_run_id INTEGER,pass_id TEXT,created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_doc_lineage_child ON doc_lineage(child_doc_id);
CREATE TABLE IF NOT EXISTS doc_chunks (
 id INTEGER PRIMARY KEY AUTOINCREMENT,doc_id INTEGER NOT NULL,chunk_index INTEGER NOT NULL,
 heading_path_json TEXT NOT NULL DEFAULT '[]',content TEXT NOT NULL,content_hash TEXT NOT NULL,
 token_estimate INTEGER NOT NULL DEFAULT 0,summary TEXT,embedding_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_doc_chunks_doc ON doc_chunks(doc_id);
CREATE INDEX IF NOT EXISTS idx_doc_chunks_hash ON doc_chunks(content_hash);
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
    def add_run(self, *, source_doc_id: int, new_doc_id: int, target_action: str, model: str,
                dials: Dict[str, Any], brand_score: int, latency_ms: int) -> int:
        """Record one transform run for the history/monitoring views."""
        now = dt.datetime.now(dt.timezone.utc).isoformat()
        with self._lock:
            cur = self.conn.execute(
                'INSERT INTO runs (created_at,source_doc_id,new_doc_id,target_action,model,dials_json,brand_score,latency_ms,used_model) '
                'VALUES (?,?,?,?,?,?,?,?,?)',
                (now, source_doc_id, new_doc_id, target_action, model or '',
                 json.dumps(dials, ensure_ascii=False), int(brand_score), int(latency_ms), 1 if model else 0))
            self.conn.commit(); return int(cur.lastrowid)

    def list_runs(self, limit: int = 50) -> List[sqlite3.Row]:
        return list(self.conn.execute('SELECT * FROM runs ORDER BY id DESC LIMIT ?', (limit,)))

    # --- Enrichment-pipeline persistence (v2) --------------------------------
    def add_pipeline_run(self, *, pipeline_id: str, source_doc_ids: List[int], target_action: str,
                         service: str, audience: str) -> int:
        now = dt.datetime.now(dt.timezone.utc).isoformat()
        with self._lock:
            cur = self.conn.execute(
                'INSERT INTO pipeline_runs (pipeline_id,source_doc_ids_json,target_action,service,audience,status,created_at,updated_at) '
                'VALUES (?,?,?,?,?,?,?,?)',
                (pipeline_id, json.dumps(source_doc_ids), target_action, service, audience, 'running', now, now))
            self.conn.commit(); return int(cur.lastrowid)

    def finish_pipeline_run(self, run_id: int, *, status: str, state: Dict[str, Any],
                            new_doc_id: Optional[int] = None) -> None:
        now = dt.datetime.now(dt.timezone.utc).isoformat()
        with self._lock:
            self.conn.execute(
                'UPDATE pipeline_runs SET status=?, state_json=?, new_doc_id=?, updated_at=?, completed_at=? WHERE id=?',
                (status, json.dumps(state, ensure_ascii=False), new_doc_id, now, now, run_id))
            self.conn.commit()

    def add_pass_run(self, pipeline_run_id: int, report: Dict[str, Any]) -> int:
        now = dt.datetime.now(dt.timezone.utc).isoformat()
        with self._lock:
            cur = self.conn.execute(
                'INSERT INTO pass_runs (pipeline_run_id,pass_id,status,mode,model,report_json,latency_ms,created_at) '
                'VALUES (?,?,?,?,?,?,?,?)',
                (pipeline_run_id, report.get('pass_id', ''), report.get('status', ''), report.get('mode', ''),
                 report.get('model', ''), json.dumps(report, ensure_ascii=False), int(report.get('latency_ms', 0)), now))
            self.conn.commit(); return int(cur.lastrowid)

    def add_doc_lineage(self, *, parent_doc_id: Optional[int], child_doc_id: int, relationship: str,
                        pipeline_run_id: Optional[int] = None, pass_id: str = '') -> int:
        now = dt.datetime.now(dt.timezone.utc).isoformat()
        with self._lock:
            cur = self.conn.execute(
                'INSERT INTO doc_lineage (parent_doc_id,child_doc_id,relationship,pipeline_run_id,pass_id,created_at) '
                'VALUES (?,?,?,?,?,?)',
                (parent_doc_id, child_doc_id, relationship, pipeline_run_id, pass_id, now))
            self.conn.commit(); return int(cur.lastrowid)

    def replace_doc_chunks(self, doc_id: int, chunks: List[Any]) -> int:
        """Idempotently store a doc's chunks (delete-then-insert). Accepts DocChunk
        objects or dicts with the same attributes."""
        def g(c, k):
            return c.get(k) if isinstance(c, dict) else getattr(c, k)
        with self._lock:
            self.conn.execute('DELETE FROM doc_chunks WHERE doc_id=?', (doc_id,))
            for c in chunks:
                self.conn.execute(
                    'INSERT INTO doc_chunks (doc_id,chunk_index,heading_path_json,content,content_hash,token_estimate,summary,embedding_json) '
                    'VALUES (?,?,?,?,?,?,?,?)',
                    (doc_id, int(g(c, 'chunk_index')), json.dumps(g(c, 'heading_path')), g(c, 'content'),
                     g(c, 'content_hash'), int(g(c, 'token_estimate')), None, None))
            self.conn.commit()
        return len(chunks)

    def get_doc_chunks(self, doc_id: int) -> List[sqlite3.Row]:
        return list(self.conn.execute('SELECT * FROM doc_chunks WHERE doc_id=? ORDER BY chunk_index', (doc_id,)))

    def list_pipeline_runs(self, limit: int = 50) -> List[sqlite3.Row]:
        return list(self.conn.execute('SELECT * FROM pipeline_runs ORDER BY id DESC LIMIT ?', (limit,)))

    def get_pipeline_run(self, run_id: int) -> Optional[sqlite3.Row]:
        return self.conn.execute('SELECT * FROM pipeline_runs WHERE id=?', (run_id,)).fetchone()

    def list_pass_runs(self, pipeline_run_id: int) -> List[sqlite3.Row]:
        return list(self.conn.execute('SELECT * FROM pass_runs WHERE pipeline_run_id=? ORDER BY id', (pipeline_run_id,)))

    def service_coverage(self, services: List[str]) -> List[Dict[str, Any]]:
        """Per-service doc counts split into VAS-owned vs reference, for gap analysis."""
        out = []
        for s in services:
            if s == 'unknown':
                continue
            total = self.count_docs(service=s)
            owned = self.count_docs(service=s, source_org='vainasherstudios')
            out.append({'service': s, 'total': total, 'owned': owned, 'reference': total - owned})
        return out

    def run_summary(self) -> Dict[str, Any]:
        """Aggregate stats for the monitoring dashboard: throughput, latency, brand."""
        row = self.conn.execute(
            'SELECT COUNT(*) n, AVG(latency_ms) lat, AVG(CASE WHEN brand_score>=0 THEN brand_score END) brand, '
            'SUM(used_model) modelled FROM runs').fetchone()
        n = int(row['n'] or 0)
        return {'count': n, 'avg_latency_ms': int(row['lat'] or 0),
                'avg_brand_score': round(row['brand'], 1) if row['brand'] is not None else None,
                'with_model': int(row['modelled'] or 0)}

    def breakdown(self, field: str, limit: int = 30) -> List[Tuple[str, int]]:
        """Counts grouped by one indexed field, biggest first — used by the monitoring
        dashboard. Whitelisted to indexed columns to keep the f-string injection-safe."""
        if field not in DENORM_FIELDS + ('review_status', 'source'):
            raise ValueError(f'not a groupable field: {field}')
        rows=self.conn.execute(f"SELECT {field} k, COUNT(*) n FROM docs GROUP BY {field} ORDER BY n DESC LIMIT ?", (limit,)).fetchall()
        return [(r['k'] or '(none)', int(r['n'])) for r in rows]
