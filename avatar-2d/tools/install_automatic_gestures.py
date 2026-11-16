"""Reproducible Avatar2D-only native integration. Back up source, never user data."""
import ast
import hashlib
import json
from datetime import datetime
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
FAY=ROOT/'fay-ue4/runtime/fay-local/app'
SERVICE=ROOT/'avatar-2d/service'
MARK='# avatar-automatic-gestures-v1'
IMPORT=MARK+'''
import sys as _gesture_sys
from pathlib import Path as _GesturePath
_gesture_service = str(_GesturePath(__file__).resolve().parents[5]/'avatar-2d/service')
if _gesture_service not in _gesture_sys.path: _gesture_sys.path.insert(0, _gesture_service)
import gesture_planner as avatar_gestures
'''

def replace(text,old,new):
    assert text.count(old)==1,(old[:100],text.count(old))
    return text.replace(old,new)

def transform_core(s):
    s=replace(s,'from core.action_signal import resolve_action_signal','from core.action_signal import resolve_action_signal\n'+IMPORT)
    begin=s.index('        if not no_reply:',s.index('    def on_interact('))
    end=s.index('        if interact.interact_type == 1:',begin)
    s=s[:begin]+'''        if not no_reply:
            try:
                from utils.stream_state_manager import get_state_manager
                from contextlib import nullcontext
                import uuid
                # Register before mutating shared streams. A delayed old HTTP
                # request must never clear or replace a newer native turn.
                with avatar_gestures.LOCK if username == 'Avatar2D' else nullcontext():
                    conv_id = "conv_" + str(uuid.uuid4())
                    accepted = avatar_gestures.register_request(username, conv_id, interact.data.get('avatar_context'),
                                                               interact.data.get('msg') or interact.data.get('text',''))
                    if username == 'Avatar2D' and not accepted:
                        return 'stale'
                    if get_state_manager().is_session_active(username):
                        stream_manager.new_instance().clear_Stream_with_audio(username)
                    stream_manager.new_instance().set_current_conversation(username, conv_id)
                    interact.data["conversation_id"] = conv_id
                    stream_manager.new_instance().set_stop_generation(username, stop=False)
            except Exception:
                util.log(3, "开启新会话失败")
                if username == 'Avatar2D':return 'stale'

'''+s[end:]
    s=replace(s,'text = nlp_cognitive_stream.question(interact.data["msg"], username, interact.data.get("observation", None))',
        '''text = nlp_cognitive_stream.question(interact.data["msg"], username, interact.data.get("observation", None),
                            avatar_conversation_id=interact.data.get('conversation_id')) if username == 'Avatar2D' else nlp_cognitive_stream.question(interact.data["msg"], username, interact.data.get("observation", None))''')
    s=replace(s,"'action': resolve_action_signal(filtered_text)","'action': avatar_gestures.signal(interact.data.get('user'), interact.data.get('conversation_id')) if interact.data.get('user')=='Avatar2D' else resolve_action_signal(filtered_text)")
    s=replace(s,'action_signal = resolve_action_signal(text)',"action_signal = avatar_gestures.signal(interact.data.get('user'), interact.data.get('conversation_id')) if interact.data.get('user')=='Avatar2D' else resolve_action_signal(text)")
    return s

def transform_gui(s):
    s=IMPORT+'\n'+s
    for stream in ('True','False'):
        old="'observation': str(observation), 'stream':"+stream+'}'
        s=replace(s,old,"'observation': str(observation), 'stream':"+stream+", 'avatar_context': data.get('avatar_context')}")
    s=replace(s,"        username = data.get('username', 'User')\n        stream_manager.new_instance().clear_Stream_with_audio(username)","        username = data.get('username', 'User')\n        avatar_gestures.invalidate(username)\n        stream_manager.new_instance().clear_Stream_with_audio(username)")
    s=replace(s,"            success = fay_booter.feiFei.on_interact(interact)","            interact.data['avatar_context'] = data.get('avatar_context')\n            success = fay_booter.feiFei.on_interact(interact)")
    s=replace(s,'        while True:\n            sentence = nlp_Stream.read()', '''        while True:
            if username == 'Avatar2D' and sm.get_conversation_id(username) != conversation_id:
                break
            if avatar_gestures.failed(username, conversation_id):
                yield 'data: '+json.dumps({'error':'数字人问答未获得合法正文，请重新提问。'})+'\\n\\n'
                break
            sentence = nlp_Stream.read()''')
    s=replace(s,'return gpt_stream_response(last_content, username)',"return gpt_stream_response(last_content, username, interact.data.get('conversation_id'))")
    s=replace(s,"            return gpt_stream_response(last_content, username, interact.data.get('conversation_id'))",'''            if username == 'Avatar2D' and not interact.data.get('conversation_id'):
                return jsonify({'error':'This avatar turn is stale'}), 409
            return gpt_stream_response(last_content, username, interact.data.get('conversation_id'))''')
    s=replace(s,'def gpt_stream_response(last_content, username):','def gpt_stream_response(last_content, username, native_conversation_id=None):')
    s=replace(s,'    def generate():\n        conversation_id = sm.get_conversation_id(username)', '''    bound_conversation = native_conversation_id or sm.get_conversation_id(username)
    def generate():
        conversation_id = bound_conversation''')
    return s

def transform_nlp(s):
    s=replace(s,'import os\n','import os\n'+IMPORT+'\n')
    s=replace(s,'def question(content, username, observation=None):','def question(content, username, observation=None, avatar_conversation_id=None):')
    s=replace(s,'    global agents, current_username\n    current_username = username', '''    global agents, current_username
    if username == 'Avatar2D' and avatar_conversation_id and not avatar_gestures.is_current(username, avatar_conversation_id):
        return ""
    current_username = username''')
    s=replace(s,'    conversation_id = sm.get_conversation_id(username)\n    set_session(username, conversation_id)',
        "    conversation_id = avatar_conversation_id if username == 'Avatar2D' and avatar_conversation_id else sm.get_conversation_id(username)\n    set_session(username, conversation_id)")
    s=replace(s,'    messages = _build_judge_messages(state)','''    messages = _build_judge_messages(state)
    avatar_username = state.get('context', {}).get('username', 'User')
    if avatar_username == 'Avatar2D' and stream_callback is not None:
        conv = state.get('context', {}).get('avatar_conversation_id') or stream_manager.new_instance().get_conversation_id(avatar_username)
        if _timing: _timing.mark('llm_request_start')
        return avatar_gestures.judge_decision(llm, messages, avatar_username, conv,
                                             stream_callback, on_tool_detected, _timing)''')
    assert s.count('stream_response_chunks(timed_chunks(llm.stream(final_messages),timing))')==2
    s=s.replace('stream_response_chunks(timed_chunks(llm.stream(final_messages),timing))',
                'stream_response_chunks(timed_chunks(avatar_gestures.reply_stream(llm,final_messages,username,conversation_id,timing),timing))')
    s=replace(s,'        # 复用原 conversation_id','''        if username == 'Avatar2D' and not avatar_gestures.is_current(username, conv_id):
            return
        # 复用原 conversation_id''')
    s=replace(s,"        if username == 'Avatar2D' and not avatar_gestures.is_current(username, conv_id):\n            return\n        # 复用原 conversation_id\n        sm.set_current_conversation(username, conv_id)\n        sm.set_stop_generation(username, stop=False)",'''        from contextlib import nullcontext
        with avatar_gestures.LOCK if username == 'Avatar2D' else nullcontext():
            if username == 'Avatar2D' and not avatar_gestures.is_current(username, conv_id):
                return
            sm.set_current_conversation(username, conv_id)
            sm.set_stop_generation(username, stop=False)''')
    s=replace(s,'            "tool_registry": tool_registry,','            "tool_registry": tool_registry,\n            "avatar_conversation_id": conversation_id,')
    s=replace(s,'            for chunk in small_llm.stream(messages):\n                flush_text = getattr(chunk, "content", None)',
                '''            for chunk in avatar_gestures.reply_stream(small_llm,messages,username,conv_id):
                flush_text = chunk if isinstance(chunk,str) else getattr(chunk, "content", None)''')
    s=replace(s,'            error_message = "抱歉，我现在太忙了，休息一会，请稍后再试。"', '''            if username == 'Avatar2D' and avatar_gestures.failed(username, conversation_id):
                full_response_text = ""
                accumulated_text = ""
                return False
            error_message = "抱歉，我现在太忙了，休息一会，请稍后再试。"''')
    s=replace(s,'        error_reply = "抱歉，我的大脑暂时开了小差，请稍后再试一下。"', '''        if username == 'Avatar2D' and avatar_gestures.failed(username, conversation_id):
            finalize_stream(force_end=True)
            return _end_session_and_remember("")
        error_reply = "抱歉，我的大脑暂时开了小差，请稍后再试一下。"''')
    return s

def main():
    backup=ROOT/'avatar-2d/runtime/automatic-gestures/native-patches'/datetime.now().strftime('%Y%m%d-%H%M%S')
    changes=[];prepared=[]
    for rel,transform in [('core/fay_core.py',transform_core),('gui/flask_server.py',transform_gui),('llm/nlp_cognitive_stream.py',transform_nlp)]:
        path=FAY/rel;old=path.read_text(encoding='utf-8-sig')
        if MARK in old:continue
        new=transform(old);ast.parse(new);prepared.append((rel,path,old,new))
    for rel,path,old,new in prepared:
        saved=backup/rel;saved.parent.mkdir(parents=True,exist_ok=True);saved.write_text(old,encoding='utf-8')
        path.write_text(new,encoding='utf-8')
        changes.append(dict(file=rel,before_sha256=hashlib.sha256(old.encode()).hexdigest(),after_sha256=hashlib.sha256(new.encode()).hexdigest()))
    if changes:
        (backup/'manifest.json').write_text(json.dumps(changes,indent=2),encoding='utf-8')
    print(json.dumps({'patched':len(changes),'backup':str(backup)},ensure_ascii=True))

if __name__=='__main__':main()

