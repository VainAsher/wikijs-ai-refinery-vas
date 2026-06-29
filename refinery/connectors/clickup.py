import requests, markdownify
from typing import Iterable
from .base import Connector
from refinery.core import SourceDoc
class ClickUpConnector(Connector):
    name='clickup'; required_config=['token','workspace_id']
    def fetch(self,limit:int=0)->Iterable[SourceDoc]:
        self.validate(); h={'Authorization':self.config['token'],'Content-Type':'application/json'}; ws=self.config['workspace_id']; r=requests.get(f'https://api.clickup.com/api/v3/workspaces/{ws}/docs?deleted=false&archived=false&limit={min(limit or 50,50)}',headers=h,timeout=30); r.raise_for_status(); count=0
        for d in r.json().get('docs',[]):
            did=d.get('id'); dr=requests.get(f'https://api.clickup.com/api/v3/workspaces/{ws}/docs/{did}',headers=h,timeout=30); dr.raise_for_status(); detail=dr.json(); html=detail.get('content','') or detail.get('html','') or f"<p>{detail.get('description','No content available.')}</p>"
            yield SourceDoc(title=d.get('name') or detail.get('name') or 'Untitled ClickUp Doc',content=markdownify.markdownify(html,heading_style='ATX'),source='clickup',source_id=str(did or ''),source_url=str(d.get('url') or detail.get('url') or ''),original_updated_at=str(d.get('date_updated') or detail.get('date_updated') or ''),raw_metadata={'summary':d,'detail':detail})
            count+=1
            if limit and count>=limit: return
