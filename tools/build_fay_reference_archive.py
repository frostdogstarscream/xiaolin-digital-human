"""Build an offline reader from browser-observed public Fay documents.

No network, credentials, runtime configuration changes, or downloaded code execution.
"""
import hashlib
import html
import json
import re
import shutil
from collections import Counter
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parents[1]/'docs/fay-reference/public-wiki-2026-11-03'
DOWNLOADS = Path.home()/'Downloads'


def clean(text):
    return text.replace('\u200b', '').replace('\u2060', '').strip()


def expected_attachments(pages):
    items = []
    for page in pages:
        for block in page['blocks']:
            is_file = 'file-block' in block['type'] or 'fallback-async-file' in block['type']
            if not is_file and not ('view-block' in block['type'] and len(block['text']) < 400):
                continue
            lines = [clean(t) for t in block['text'].splitlines() if clean(t)]
            filename = next((t for t in lines if re.search(r'\.(zip|md|xml|kt|java|docx)$', t, re.I)), None)
            if not is_file and not filename:
                continue
            items.append(dict(page_title=page['title'], page_url=page['url'],
                              filename=filename, displayed_text=clean(block['text'])))
    return items


def main():
    inventory = json.loads((ROOT/'inventory.json').read_text(encoding='utf-8'))
    pages = [json.loads((ROOT/'pages'/f"{i['token']}.json").read_text(encoding='utf-8')) for i in inventory]
    assert len(pages) == 64 and all(p['status'] == 'TEXT_CAPTURED_TO_END' for p in pages)
    attachments = expected_attachments(pages)
    (ROOT/'attachments').mkdir(exist_ok=True)
    for item in attachments:
        name = item['filename']
        if not name:
            item['status'] = 'MEDIA_OR_APPLICATION_REFERENCE_ONLY'
            continue
        source = DOWNLOADS/name
        target = ROOT/'attachments'/name
        if source.is_file() and not target.exists():
            shutil.copy2(source, target)
        if target.is_file():
            if target.suffix.lower() in ('.zip', '.docx'):
                with ZipFile(target) as archive:
                    assert archive.testzip() is None, name
            item.update(status='SAVED', relative_path=target.relative_to(ROOT).as_posix(),
                        bytes=target.stat().st_size, sha256=hashlib.sha256(target.read_bytes()).hexdigest())
        else:
            item['status'] = 'NOT_DOWNLOADED'
    (ROOT/'attachments.json').write_text(json.dumps(attachments, ensure_ascii=False, indent=2), encoding='utf-8')

    # Extract the manifest/scripts of successfully downloaded course packages as data.
    courses = []
    for item in attachments:
        if item.get('status') != 'SAVED' or not item['filename'].lower().endswith('.zip'):
            continue
        with ZipFile(ROOT/item['relative_path']) as archive:
            if 'manifest.json' not in archive.namelist():
                continue
            manifest = json.loads(archive.read('manifest.json').decode('utf-8-sig'))
            destination = ROOT/'courses'/Path(item['filename']).stem
            destination.mkdir(parents=True, exist_ok=True)
            chapters = []
            for section in manifest.get('sections', []):
                member = section.get('script')
                if not member or member not in archive.namelist():
                    continue
                script = archive.read(member).decode('utf-8-sig')
                chapters.append(f"## {section.get('title', section.get('id', ''))}\n\n{script}")
            (destination/'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
            (destination/'课程正文.md').write_text('# '+manifest.get('title', item['filename'])+'\n\n'+'\n\n'.join(chapters), encoding='utf-8')
            courses.append(dict(title=manifest.get('title'), version=manifest.get('version'), chapters=len(chapters),
                                archive=item['relative_path'], text=(destination/'课程正文.md').relative_to(ROOT).as_posix()))

    embedded_only = [p['title'] for p in pages if any('iframe-block' in b['type'] for b in p['blocks']) and p['chars'] < 10]
    empty = [p['title'] for p in pages if p['title'] not in embedded_only and not clean(''.join(b['text'] for b in p['blocks']))]
    body_chars = sum(p['chars'] for p in pages)
    type_counts = Counter(b['type'].split('docx-')[-1].split('-block')[0] for p in pages for b in p['blocks'])
    report = dict(scope='Fay public wiki sidebar and all expanded descendants', page_count=len(pages),
                  pages_reached_end=64, rendered_text_characters=body_chars,
                  source_empty_pages=empty, embedded_only_pages=embedded_only,
                  attachment_statuses=dict(Counter(i['status'] for i in attachments)), courses=courses,
                  block_types=dict(type_counts), images_ocr=False, videos_transcribed=False,
                  remote_images_bulk_downloaded=False, fay_runtime_modified=False)
    report['structured_tables'] = sum(bool(b.get('table_rows')) for p in pages for b in p['blocks'])
    report['structured_table_cells'] = sum(len(row) for p in pages for b in p['blocks'] for row in b.get('table_rows', []))
    (ROOT/'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')

    progress = [{k:p[k] for k in ('title','token','url','status','chars','scroll_samples')} for p in pages]
    (ROOT/'capture-progress.json').write_text(json.dumps(progress,ensure_ascii=False,indent=2),encoding='utf-8')
    md = ['# Fay 公开知识库离线正文', '',
          f'采集日期：2026-11-03。共 {len(pages)} 页，网页文字约 {body_chars:,} 字符。', '',
          '范围：从公开知识库目录逐层展开得到的全部页面。逐页滚动至页尾，保留文字块与来源链接。图片中的文字未 OCR，视频未转写；本资料不是所有媒体及二进制文件的完整镜像。', '']
    sections = []
    nav = []
    for page in pages:
        text = '\n\n'.join(clean(b['text']) or ('[图片，未 OCR]' if 'image-block' in b['type'] else '[嵌入视频或外部页面]' if 'iframe-block' in b['type'] else '[媒体]' if 'video' in b['type'] else '') for b in page['blocks'])
        if page['title'] in empty:
            text = '[已复核：来源页面没有正文。]'
        if page['title'] in embedded_only:
            text += '\n\n来源仅嵌入 B 站视频：https://player.bilibili.com/player.html?autoplay=0&bvid=1PF4m1u7KX'
        links = list(dict.fromkeys(link['href'] for b in page['blocks'] for link in b.get('links', []) if link.get('href')))
        visible_links = [u for u in links if u.startswith(('https://','http://')) and u not in text]
        if visible_links:
            text += '\n\n页面引用链接：\n'+'\n'.join(visible_links)
        markdown = '# '+page['title']+'\n\n来源：'+page['url']+'\n\n'+text+'\n'
        (ROOT/'pages'/f"{page['token']}.md").write_text(markdown, encoding='utf-8')
        md += ['---', '', '## '+page['title'], '', '来源：'+page['url'], '', text, '']
        token = page['token']
        title = html.escape(page['title'])
        sections.append(f'<article id="{token}" data-title="{title}"><h2>{title}</h2><p class="source"><a href="{page["url"]}" target="_blank" rel="noreferrer">飞书原文 ↗</a> · {page["chars"]:,} 字符 · 已滚动至页尾</p><pre>{html.escape(text)}</pre></article>')
        nav.append(f'<a href="#{token}" data-token="{token}" style="padding-left:{14+max(0,page["level"]-1)*12}px">{title}</a>')
    (ROOT/'全部正文.md').write_text('\n'.join(md), encoding='utf-8')
    saved_count = sum(i['status']=='SAVED' for i in attachments)
    attachment_rows = []
    for item in attachments:
        label = item['filename'] or item['displayed_text'].splitlines()[0]
        state = {'SAVED':'已下载并校验', 'NOT_DOWNLOADED':'未下载，保留原页面入口', 'MEDIA_OR_APPLICATION_REFERENCE_ONLY':'媒体／安装包，仅保留入口'}[item['status']]
        link = f'<a href="{html.escape(item["relative_path"])}" download>{html.escape(label)}</a>' if item['status']=='SAVED' else html.escape(label)
        attachment_rows.append(f'<tr><td>{link}</td><td>{state}</td><td><a href="{item["page_url"]}" target="_blank" rel="noreferrer">来源 ↗</a></td></tr>')
    page_html = '''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Fay 公开知识库 · 离线资料</title><style>
:root{font-family:"Microsoft YaHei UI",sans-serif;color:#26333f;background:#f5f7fa}*{box-sizing:border-box}body{margin:0}aside{position:fixed;width:290px;height:100vh;background:#fff;border-right:1px solid #dce3ea;overflow:auto;padding:22px 0}aside h2{font-size:17px;padding:0 16px}aside input{width:calc(100% - 28px);margin:0 14px 14px;padding:11px;border:1px solid #c5ced8;border-radius:7px}nav a{display:block;font-size:12px;line-height:1.6;padding:7px 14px;text-decoration:none;color:#33465a}nav a:hover{background:#eaf2ff}main{margin-left:290px;max-width:1450px;padding:32px 42px}h1{font-size:29px;margin:0 0 12px}p{line-height:1.8}a{color:#1768ba}.lead{color:#536577}.stats{display:flex;gap:12px;flex-wrap:wrap;margin:23px 0}.stats div{background:#fff;border:1px solid #dce3ea;padding:17px 21px;border-radius:10px;min-width:150px}.stats strong{display:block;font-size:25px;color:#1367b4}.stats span{font-size:12px;color:#6a7b8c}.note{background:#edf3fb;border-left:4px solid #497fb8;padding:15px 18px;font-size:13px;line-height:1.9}article{background:#fff;border:1px solid #dce3ea;border-radius:10px;margin:22px 0;padding:24px;scroll-margin-top:20px}article h2{font-size:20px;margin:0 0 8px}.source{font-size:12px;color:#66798b}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:14px/1.9 "Microsoft YaHei UI",sans-serif}table{width:100%;border-collapse:collapse;font-size:12px;background:#fff}td,th{text-align:left;padding:10px;border-bottom:1px solid #e2e8ee}details{margin-top:24px}summary{cursor:pointer;font-weight:bold}.empty{padding:30px;color:#666}@media(max-width:800px){aside{position:static;width:auto;height:auto;max-height:40vh;border-bottom:1px solid #ddd}main{margin-left:0;padding:22px 14px}}
</style><aside><h2>Fay 公开知识库</h2><input id="search" placeholder="搜索标题或正文…" aria-label="搜索知识库"><nav>__NAV__</nav></aside><main><h1>Fay 公开知识库 · 离线资料</h1><p class="lead">公开目录逐页归档 · 2026-11-03 · 保留飞书原文入口</p><div class="stats"><div><strong>64 / 64</strong><span>公开页面已采集至页尾</span></div><div><strong>__CHARS__</strong><span>网页文字字符</span></div><div><strong>__SAVED__</strong><span>附件实际下载并校验</span></div><div><strong>4</strong><span>来源空白页已复核</span></div></div><div class="note">正文可离线阅读和全文搜索。包含目录子页、可复制的文字与代码及原页面链接；图片未 OCR，视频未转写，远程图片未批量下载。四个空白页是“看见（CV）”“Azure tts”“ali”“volcano”；NLP 响应速度问题页仅嵌入 B 站视频。附件状态逐项列在下方，不把点击下载视为下载完成。</div><p><a href="全部正文.md" download>下载合并正文 Markdown</a> · <a href="report.json">采集报告</a> · <a href="attachments.json">附件清单</a></p><details><summary>附件与原始课程包（实际落盘状态）</summary><table><thead><tr><th>文件</th><th>状态</th><th>原页面</th></tr></thead><tbody>__ATTACHMENTS__</tbody></table></details><p id="count">显示全部 64 页</p>__SECTIONS__</main><script>
const input=document.getElementById('search'),articles=[...document.querySelectorAll('article')],links=[...document.querySelectorAll('nav a')];input.addEventListener('input',()=>{const q=input.value.trim().toLowerCase();let count=0;articles.forEach((a,i)=>{const match=!q||a.textContent.toLowerCase().includes(q);a.hidden=!match;links[i].hidden=!match;if(match)count++;});document.getElementById('count').textContent='显示 '+count+' / 64 页';});
</script></html>'''
    page_html = page_html.replace('__NAV__',''.join(nav)).replace('__CHARS__',f'{body_chars:,}').replace('__SAVED__',str(saved_count)).replace('__ATTACHMENTS__',''.join(attachment_rows)).replace('__SECTIONS__',''.join(sections))
    page_html = page_html.replace('</style>','[hidden]{display:none!important}</style>')
    (ROOT/'index.html').write_text(page_html, encoding='utf-8')
    readme = f'''# Fay 公开知识库离线资料

打开 `index.html` 可阅读并搜索全部正文，也可查看 `全部正文.md`。

- 公开目录：64 个页面，全部逐页滚动至末尾，网页文字 {body_chars:,} 字符。
- 来源、层级、正文块、采集时间：`inventory.json`、`pages/*.json`。
- 单篇正文：`pages/*.md`。
- 附件：实际保存 {saved_count} 份，详细 SHA256、大小、下载状态见 `attachments.json`。
- 原始课程：已下载的 ZIP 原样保留；可解析的课程清单和讲稿在 `courses/`。
- 限制：图片未 OCR、视频未转写、远程图片未批量下载。媒体与 APK 只保留页面入口。这是网页文字归档，不是全部媒体及软件的镜像。
- 四页本身无正文：{'、'.join(empty)}。一页仅为外部视频嵌入：{'、'.join(embedded_only)}。
- 只整理资料，没有修改正在运行的 Fay、模型、TTS、ASR 或数字人。

`report.json` 是汇总报告；`checksums.json` 是本地文件校验清单。
'''
    (ROOT/'README.md').write_text(readme, encoding='utf-8')
    checksums = {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(ROOT.rglob('*')) if p.is_file() and p.name!='checksums.json'}
    (ROOT/'checksums.json').write_text(json.dumps(checksums, ensure_ascii=False, indent=2), encoding='utf-8')
    output = ROOT.parent/'Fay-public-wiki-2026-11-03.zip'
    with ZipFile(output,'w',ZIP_DEFLATED) as archive:
        for path in ROOT.rglob('*'):
            if path.is_file():archive.write(path,ROOT.name+'/'+path.relative_to(ROOT).as_posix())
    print(json.dumps(dict(pages=len(pages),characters=body_chars,attachments=saved_count,empty_pages=empty,
                          zip_bytes=output.stat().st_size,zip_sha256=hashlib.sha256(output.read_bytes()).hexdigest()),ensure_ascii=True))


if __name__=='__main__':main()
