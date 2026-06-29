import re, requests, markdownify
from typing import Iterable
from .base import Connector
from refinery.core import SourceDoc
class ZendeskConnector(Connector):
    name='zendesk'; required_config=['url']
    def fetch(self,limit:int=0)->Iterable[SourceDoc]:
        self.validate(); zd=self.config['url'].strip(); zd='https://'+zd if not zd.startswith(('http://','https://')) else zd; base=re.search(r'https?://[^/]+',zd).group(0); url=f'{base}/api/v2/help_center/en-us/articles.json?per_page=100'; count=0
        while url:
            r=requests.get(url,headers={'User-Agent':'WikiJS-AI-Refinery/1.0','Accept':'application/json'},timeout=30); r.raise_for_status(); data=r.json()
            for a in data.get('articles',[]):
                html=a.get('body') or ''
                if not html: continue
                yield SourceDoc(title=a.get('title') or 'Untitled Zendesk Article',content=markdownify.markdownify(html,heading_style='ATX'),source='zendesk',source_id=str(a.get('id') or ''),source_url=str(a.get('html_url') or base),original_updated_at=str(a.get('updated_at') or ''),raw_metadata=a)
                count+=1
                if limit and count>=limit: return
            url=data.get('next_page')
