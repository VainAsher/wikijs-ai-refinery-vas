from typing import Dict, Iterable, Any
from refinery.core import SourceDoc
class Connector:
    name='base'; required_config=[]
    def __init__(self,config:Dict[str,Any]): self.config=config
    def validate(self):
        miss=[k for k in self.required_config if not self.config.get(k)]
        if miss: raise ValueError(f'Missing required config for {self.name}: {", ".join(miss)}')
    def fetch(self,limit:int=0)->Iterable[SourceDoc]: raise NotImplementedError
