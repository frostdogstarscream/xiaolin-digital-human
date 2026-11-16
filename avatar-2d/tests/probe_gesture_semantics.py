"""Bounded text-only semantic probe of the saved small model, no business memory/TTS."""
import json
import os
import sys
import time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];FAY=ROOT.parent/'fay-ue4/runtime/fay-local/app'
for key in ('FAY_CONFIG_CENTER_ID','FAY_SYSTEM_CONF_JSON','OPENAI_API_KEY','LANGCHAIN_API_KEY','LANGSMITH_API_KEY','EMBEDDING_API_KEY'):
    os.environ.pop(key,None)
os.environ.update(LANGCHAIN_TRACING_V2='false',LANGSMITH_TRACING='false')
sys.path[:0]=[str(ROOT/'service'),str(FAY)];os.chdir(FAY)
import gesture_planner as g
from llm.execution_manager import _get_llm_instance
from langchain_core.messages import SystemMessage,HumanMessage

CASES=[
    ('first_welcome','你好，我第一次来，请欢迎我。',True,['welcome-wave']),
    ('repeat_welcome','你好，我们刚刚已经打过招呼了。简短回应即可。',False,['idle','acknowledge-nod']),
    ('goodbye','今天就到这里，我要离开了，再见。',False,['goodbye-wave']),
    ('quoted_goodbye','“再见”是什么意思？请简短解释。',False,['idle','explain-open-palms']),
    ('confirmation','我理解了，你只要确认收到，不用解释。',False,['acknowledge-nod','idle']),
    ('negation','我并不是要离开，请不要跟我告别，简单回应。',False,['idle','acknowledge-nod']),
    ('explanation','请分三点说明实时数字人如何将文字转换成说话画面，每点一句话。',False,['explain-open-palms']),
    ('short','一加一是多少？仅回答数字。',False,['idle']),
    ('no_motion','不要做任何动作。请用两句话介绍你的用途。',False,['idle']),
]

def main():
    results=[]
    for name,question,welcome,expected in CASES:
        c=g.ActionController();c.begin(1);c.welcomed=not welcome;cid='semantic-'+c.controller_id
        g.register_request('Avatar2D',cid,c.context(1))
        model=_get_llm_instance('small',True,session_id=cid)
        start=time.perf_counter();events=[];raw=[];dec=g.GestureDecoder(on_gesture=lambda x:events.append(('gesture',time.perf_counter()-start,x)))
        first=None;text=''
        messages=[SystemMessage(content='你叫小霖，是成年女性数字讲解员。请自然、简洁地回答，不输出思考过程。'),HumanMessage(content=question)]
        for chunk in g.model_stream(model,g._messages(messages,g.instruction('Avatar2D',cid))):
            if chunk.content:
                raw.append(chunk.content);delta=dec.feed(chunk.content)
                if delta and first is None:first=time.perf_counter()-start
                text+=delta
        dec.finish();gesture=dec.fields.get('gesture','idle')
        result=dict(case=name,question=question,gesture=gesture,text=text,expected=expected,passed=gesture in expected,
                    gesture_seconds=round(events[0][1],3),first_body_seconds=round(first,3),total_seconds=round(time.perf_counter()-start,3),
                    raw=''.join(raw),logical_model_calls=1,model=model.model_name)
        results.append(result)
        target=ROOT/'docs/automatic-gesture-semantics-2026-11-04.json'
        target.write_text(json.dumps(dict(results=results,passed=all(r['passed'] for r in results)),ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(result,ensure_ascii=True),flush=True)
    assert all(r['passed'] for r in results),'Inspect semantic deviations'

if __name__=='__main__':main()
