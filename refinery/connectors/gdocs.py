import markdownify
from typing import Iterable
from .base import Connector
from refinery.core import SourceDoc
class GoogleDocsConnector(Connector):
    name='gdocs'; required_config=['folder_id']
    def fetch(self,limit:int=0)->Iterable[SourceDoc]:
        self.validate()
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
        creds=service_account.Credentials.from_service_account_file(self.config.get('credentials_json','credentials.json'),scopes=['https://www.googleapis.com/auth/drive.readonly']); drive=build('drive','v3',credentials=creds); q=f"'{self.config['folder_id']}' in parents and mimeType='application/vnd.google-apps.document' and trashed=false"; token=None; count=0
        while True:
            res=drive.files().list(q=q,pageSize=100,fields='nextPageToken, files(id, name, modifiedTime, webViewLink)',pageToken=token).execute()
            for item in res.get('files',[]):
                html=drive.files().export(fileId=item['id'],mimeType='text/html').execute(); html=html.decode('utf-8') if isinstance(html,bytes) else str(html)
                yield SourceDoc(title=item.get('name') or 'Untitled Google Doc',content=markdownify.markdownify(html,heading_style='ATX',strip=['style','script']),source='gdocs',source_id=item.get('id',''),source_url=item.get('webViewLink',''),original_updated_at=item.get('modifiedTime',''),raw_metadata=item)
                count+=1
                if limit and count>=limit: return
            token=res.get('nextPageToken')
            if not token: break
