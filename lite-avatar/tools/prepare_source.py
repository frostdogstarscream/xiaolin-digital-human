"""Restore the official source at the recorded revision without editing it."""
import io
import json
import zipfile
from pathlib import Path

import requests

ROOT=Path(__file__).resolve().parents[1]
manifest=json.loads((ROOT/'source-manifest.json').read_text(encoding='utf-8'))
revision=manifest['source_revision']
destination=ROOT/'vendor/lite-avatar'
if (destination/'lite_avatar.py').exists():
    print('Pinned source already present; retained existing vendor files.')
else:
    response=requests.get('https://codeload.github.com/HumanAIGC/lite-avatar/zip/'+revision,timeout=90)
    response.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        prefix=archive.namelist()[0]
        for member in archive.infolist():
            relative=Path(member.filename.removeprefix(prefix))
            if member.is_dir():continue
            if relative.is_absolute() or '..' in relative.parts:raise RuntimeError('Unsafe source archive path')
            target=destination/relative;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(archive.read(member))
    print('Prepared official LiteAvatar source:',revision)
