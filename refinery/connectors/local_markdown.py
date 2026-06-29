from __future__ import annotations
from pathlib import Path
from typing import Iterable, Tuple, Dict, Any, List
import yaml
from .base import Connector
from refinery.core import SourceDoc

class LocalMarkdownConnector(Connector):
    name = 'local_markdown'
    required_config = ['path']

    def _sources(self) -> List[Tuple[str, Path]]:
        """Parse the path config into (label, path) pairs. Each line may be a bare
        path, or a 'label|path' / 'label=path' mapping (same syntax as the /bulk
        form), so the CLI and web UI now accept identical input. Falls back to the
        source_label config, then the directory name, when no label is given."""
        raw = str(self.config.get('path') or '')
        default_label = str(self.config.get('source_label') or '').strip()
        # Only treat source_label as a plain default if it isn't itself a mapping blob.
        if any(ch in default_label for ch in ('|', '=', '\n')):
            default_label = ''
        out: List[Tuple[str, Path]] = []
        for chunk in raw.replace(';', '\n').splitlines():
            chunk = chunk.strip()
            if not chunk or chunk.startswith('#'):
                continue
            label, path = default_label, chunk
            if '|' in chunk:
                label, path = chunk.split('|', 1)
            elif '=' in chunk:
                label, path = chunk.split('=', 1)
            label = label.strip().strip('"'); path = path.strip().strip('"')
            p = Path(path)
            out.append((label or p.name, p))
        return out

    def _read_md(self, path: Path) -> Tuple[Dict[str, Any], str]:
        raw = path.read_text(encoding='utf-8', errors='replace')
        if raw.startswith('---'):
            parts = raw.split('---', 2)
            if len(parts) == 3:
                return yaml.safe_load(parts[1]) or {}, parts[2].strip()
        return {}, raw.strip()

    def _title(self, meta: Dict[str, Any], content: str, path: Path) -> str:
        if meta.get('title'):
            return str(meta['title'])
        for line in content.splitlines():
            if line.startswith('# '):
                return line[2:].strip()
        return path.stem

    def fetch(self, limit: int = 0) -> Iterable[SourceDoc]:
        self.validate()
        count = 0
        for source_label, root in self._sources():
            if not root.exists():
                raise FileNotFoundError(f'Local Markdown path does not exist: {root}')
            for file in sorted(root.rglob('*.md')):
                meta, content = self._read_md(file)
                rel = str(file.relative_to(root)) if file.is_relative_to(root) else str(file)
                yield SourceDoc(
                    title=self._title(meta, content, file),
                    content=content,
                    source=source_label or 'local_markdown',
                    source_id=str(meta.get('source_id') or meta.get('id') or rel),
                    source_url=str(meta.get('source_url') or meta.get('url') or ''),
                    original_updated_at=str(meta.get('updated_at') or meta.get('lastmod') or ''),
                    raw_metadata={'file': str(file), 'root': str(root), 'relative_path': rel, **meta},
                )
                count += 1
                if limit and count >= limit:
                    return
