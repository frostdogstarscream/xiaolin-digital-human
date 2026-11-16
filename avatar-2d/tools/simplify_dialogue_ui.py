"""Remove obsolete presentation controls from the formal console only."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def main():
    path=ROOT/'web/live.html';s=path.read_text(encoding='utf-8')
    if 'data-mode=' in s:
        a=s.index('<h2>对话与播报</h2>');b=s.index('<div class="row">',a)
        s=s[:a]+'<h2>输入问题</h2><textarea id="text" maxlength="300" placeholder="输入问题，小霖会回答并自动选择合适的动作。"></textarea>'+s[b:]
        s=s.replace('id="send">开始播报','id="send">发送问题')
        a=s.index('<section class="card"><h2>动作控制');b=s.index('</section>',a)+len('</section>')
        s=s[:a]+'''<section class="card"><h2>动作状态</h2><div class="status-line"><span>当前动作</span><span id="action-status" class="tag">待机</span></div><p class="small">小霖会根据问题和回复意图选择动作，每轮至多一次。动作结束后保持最后姿态。</p></section>'''+s[b:]
        path.write_text(s,encoding='utf-8')
    path=ROOT/'web/live.js';s=path.read_text(encoding='utf-8')
    s=s.replace("mode='say', ",'').replace("mode='say',",'')
    s=s.replace("await api('action',{action:$('#speech-action').value});const r=await api(mode,{text});","const r=await api('chat',{text});")
    if "document.querySelectorAll('[data-mode]')" in s:
        a=s.index("document.querySelectorAll('[data-mode]')");b=s.index("$('#fullscreen').onclick",a)
        s=s[:a]+s[b:]
    s=s.replace('录音或播报功能','录音或问答功能').replace('可随时打断或切换动作','可随时打断')
    s=s.replace("    if(e.event==='playback_started')", "    if(e.event==='action_started')$('#action-status').textContent=names[e.action]||'待机';\n    if(e.event==='playback_started')")
    s=s.replace("    const currentConnected=pc?.connectionState==='connected';","    if($('#action-status'))$('#action-status').textContent=names[h.active_action]||'待机';\n    const currentConnected=pc?.connectionState==='connected';")
    path.write_text(s,encoding='utf-8')

if __name__=='__main__':main()
