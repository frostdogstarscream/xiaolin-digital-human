"""Summarize actual target receipts, retaining failed baseline and human acceptance limits."""
import hashlib,html,json,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];OUT=ROOT/'avatar-2d/outputs/1660-qwen-new-mode-20261110'
def read(name):return json.loads((OUT/name).read_text(encoding='utf-8-sig'))
functions=read('functions.json');browser=read('browser.json');cache=read('lossless-cache.json');performance=read('performance/report.json')
persistence=read('persistence.json');final=read('final-state.json');mcp=read('mcp-proof.json')
checks=dict(functions=functions['status']=='PASSED',actual_local_browser=browser['status']=='PASSED',
            lossless_cache=cache['status']=='PASSED' and sum(c['frames'] for c in cache['clips'])==1375,
            performance=performance['status']=='PASSED',persistence=persistence['status']=='PASSED',
            graceful_stop=read('graceful-exit.json')['cleanup_completed'],
            final_service=final['health']['status']=='ready',mcp_stdout=mcp['stdout_success_lines']==2)
report=dict(status='TECHNICAL_PASSED_HUMAN_ACCEPTANCE_PENDING' if all(checks.values()) else 'ACCEPTANCE_NOT_MET',
    date='2026-11-10',target=dict(host='DESKTOP-7U752RG',ssh='Admin@192.168.10.25:22',gpu='GTX 1660 6GB',ram_gb=8),
    entry='http://127.0.0.1:8771/',model='qwen-audio-3.1-realtime-flash',voice='longanqian_v3.1',checks=checks,
    cache=dict(raw_bytes=sum(c['raw_bytes'] for c in cache['clips']),compressed_bytes=sum(c['compressed_bytes'] for c in cache['clips']),pixel_exact=True),
    performance=performance,browser=browser,mcp=mcp,persistence=persistence,final=final,
    limitations=['Physical microphone, actual speaker sound and full visual experience require onsite human acceptance.',
                 'Firefox compatibility was not accepted on this host; local Edge was tested.',
                 'Five-minute performance uses fixed PCM and native local WebRTC; cloud latency cases are separate single observations.',
                 'Business knowledge and long-term memory default namespace are new and empty; acceptance data remains isolated.'],
    preservation=['Old 8766 mode and existing service credentials retained.','Existing renderer environment and model reused without package updates.',
                  'Uncompressed original frame arrays and failed memory-pressure baseline retained.','No machine reboot or public port opening.'])
(OUT/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
render=performance.get('render_fps');receive=performance.get('receive_fps');queue=performance.get('queue_last_minute',{})
guide=f'''1660 一体机小霖新模式 — 安装与验收说明
日期：2026-11-10
状态：{report['status']}

机器：DESKTOP-7U752RG，Admin@192.168.10.25:22，GTX1660 6GB，内存8GB。
入口：在一体机本机访问 http://127.0.0.1:8771/。
桌面：双击“启动小霖新模式”；结束时双击“停止小霖新模式”。采用手动启动，SSH断开后持续运行。
进入后点击“开启实时对话”并允许麦克风权限即可直接说话；当前新模式无需唤醒词。人物画面右下角提供全屏按钮，Esc或退出按钮返回。
模型：qwen-audio-3.1-realtime-flash，音色longanqian_v3.1；沿用本机已有百炼配置。
模型与能力：协同总开关以及MCP打卡、业务知识库、关联记忆、自动手势默认全部开启，保存后下一轮生效。
知识与记录：可录入业务文本。沿用付费Pro/BAAI/bge-m3及Pro/BAAI/bge-reranker-v2-m3。当前真实业务库为空，记忆单独初始化；未迁移云端或旧模式历史。

功能验收：实际文本及冻结语音均通过实时模型调用MCP，两次实际执行均有success输出；否定咨询及关闭总开关不执行。实际付费资料检索、断开模型连接后召回记忆通过。真实音视频输出1080×1920，本机Edge画面和全屏/退出通过。
持续验收：服务端渲染 {render} fps，原生WebRTC接收 {receive} fps；末分钟队列统计 {json.dumps(queue,ensure_ascii=False)}。详见performance/report.json。
初始普通数组缓存因8GB内存压力出现持续积压，已保留失败基线。最终使用逐帧Zstandard无损缓存，1375帧逐帧校验像素完全一致，保持1080×1920、25fps、FP32、batch4，原始数组没有删除。
持久化：停止、启动后模型开关和记忆数量保持，正常清理退出验证见graceful-exit.json。MCP只是占位测试，不连接真实考勤。

人工验收待办：真实麦克风收音、扬声器实际声音、回声与完整动态观感。本机浏览器验收为Edge，不将此前未完成的Firefox测试算作通过。
旧模式仍保留在8766。8GB机器请一次只运行一种数字人模式，新模式不会强行停止正在运行的旧模式。

安装根目录：D:\\XiaolinDigitalHuman
代码：avatar-2d\\experiments\\qwen-realtime-v2 与 presenter-v2-1080
数据：avatar-2d\\runtime\\qwen-realtime-v2（设置、独立记忆库、进程记录及日志）
控制：deployment\\qwen-new-mode-20261110\\Control-Qwen.ps1 -Action Start|Stop|Status
报告：deployment\\qwen-new-mode-20261110\\reports
回退：停止新模式，使用原“启动小霖”入口；不会切换或删除旧模式数据。新缓存适配备份在deployment\\qwen-new-mode-20261110\\before-lossless-cache。
交付包不包含API Key、配置凭据、SSH私钥或真实记忆数据库。
'''
(OUT/'使用与验收说明.txt').write_text(guide,encoding='utf-8-sig')
document='<!doctype html><meta charset="utf-8"><title>1660小霖新模式验收</title><style>body{max-width:960px;margin:40px auto;font:16px/1.8 system-ui;color:#20343e;padding:20px}pre{white-space:pre-wrap;background:#f2f6f8;padding:24px;border-radius:10px}img{max-width:100%}</style><h1>1660 小霖新模式</h1><pre>'+html.escape(guide)+'</pre><img src="browser-fullscreen.jpg" alt="一体机本机全屏画面">'
(OUT/'验收报告.html').write_text(document,encoding='utf-8')
bundle=OUT/'1660-xiaolin-new-mode-delivery.zip'
with zipfile.ZipFile(bundle,'w',zipfile.ZIP_DEFLATED) as z:
    for p in OUT.rglob('*'):
        if p.is_file() and p.suffix in {'.json','.txt','.html','.jpg','.log'}:z.write(p,'evidence/'+p.relative_to(OUT).as_posix())
    for p in Path(__file__).parent.iterdir():
        if p.is_file() and p.suffix in {'.py','.ps1'}:z.write(p,'deployment-source/'+p.name)
(OUT/'delivery.sha256').write_text(hashlib.sha256(bundle.read_bytes()).hexdigest()+'  '+bundle.name+'\n')
print(json.dumps(dict(status=report['status'],checks=checks,delivery=str(bundle)),ensure_ascii=False))
