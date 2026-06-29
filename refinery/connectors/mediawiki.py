import requests, markdownify
from typing import Iterable
from .base import Connector
from refinery.core import SourceDoc
class MediaWikiConnector(Connector):
    name='mediawiki'; required_config=['api_url']
    def fetch(self,limit:int=0)->Iterable[SourceDoc]:
        self.validate(); s=requests.Session(); s.headers.update({'User-Agent':'WikiJS-AI-Refinery/1.0'}); 
        if self.config.get('cookie'): s.headers.update({'Cookie':self.config['cookie']})
        api=self.config['api_url']; cont=None; count=0
        while True:
            params={'action':'query','list':'allpages','aplimit':500,'apnamespace':int(self.config.get('namespace',0)),'format':'json'}
            if cont: params['apcontinue']=cont
            data=s.get(api,params=params,timeout=30).json()
            for p in data.get('query',{}).get('allpages',[]):
                title=p['title']; pr=s.get(api,params={'action':'parse','page':title,'prop':'text','format':'json','disableeditsection':True,'disabletoc':True},timeout=30); pr.raise_for_status(); html=pr.json().get('parse',{}).get('text',{}).get('*','')
                if not html: continue
                yield SourceDoc(title=title,content=markdownify.markdownify(html,heading_style='ATX'),source='mediawiki',source_id=str(p.get('pageid') or ''),raw_metadata=p)
                count+=1
                if limit and count>=limit: return
            cont=data.get('continue',{}).get('apcontinue')
            if not cont: break
