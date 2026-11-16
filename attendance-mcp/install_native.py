"""Scoped reproducible source integration, backed up before touching native Fay."""
import ast
import hashlib
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
BACKUP=ROOT/'attendance-mcp/runtime/before'
MARK='# avatar-attendance-mcp-v1'

def replace(s,old,new):
    assert s.count(old)==1,(old[:90],s.count(old));return s.replace(old,new)

def transform_nlp(s):
    s=replace(s,'import gesture_planner as avatar_gestures','import gesture_planner as avatar_gestures\nimport attendance_policy\n'+MARK)
    s=replace(s,'        # 刷出剩余文本\n        if accumulated:', '''        if username == 'Avatar2D' and not avatar_gestures.is_current(username, conv_id):
            return
        # 刷出剩余文本
        if accumulated:''')
    s=replace(s,'        exec_mgr.consume_result(username)\n\n', '''        if username != 'Avatar2D' or avatar_gestures.is_current(username, conv_id):
            exec_mgr.consume_result(username)

''')
    # Keep execution logs out of the Avatar chat/voice path. Native other clients retain them.
    s=replace(s,'        full_text = think_tag  # think 标签作为完整文本的开头',"        full_text = '' if username == 'Avatar2D' else think_tag")
    s=replace(s,'        _write(think_tag, force_first=is_first)',"        if username != 'Avatar2D':_write(think_tag, force_first=is_first)")
    return s

def transform_execution(s):
    s=replace(s,'from utils import util', '''from utils import util
'''+MARK+'''
import sys as _attendance_sys
from pathlib import Path as _AttendancePath
_attendance_path=str(_AttendancePath(__file__).resolve().parents[5]/'avatar-2d/service')
if _attendance_path not in _attendance_sys.path:_attendance_sys.path.insert(0,_attendance_path)
import attendance_policy''')
    s=replace(s,'        success, output, error = spec.executor(tool_args, attempts)',
        '        success, output, error = attendance_policy.invoke_once(state, spec, tool_args, attempts)')
    s=replace(s,'        # 大模型决策下一步（使用专用的执行 prompt）', '''        if state.username == 'Avatar2D' and tool_name == attendance_policy.TOOL and attendance_policy.installed():
            state.final_response_hint = "占位打卡测试成功。" if success else "占位打卡测试未完成，请说明失败。"
            break
        # 大模型决策下一步（使用专用的执行 prompt）''')
    return s

def transform_gui(s):
    s=replace(s,'import gesture_planner as avatar_gestures','import gesture_planner as avatar_gestures\nimport attendance_policy\n'+MARK)
    return replace(s,'        avatar_gestures.invalidate(username)','        attendance_policy.cancel_turn(username)\n        avatar_gestures.invalidate(username)')

def main():
    changes=[];prepared=[]
    for rel,transform in [('llm/nlp_cognitive_stream.py',transform_nlp),('llm/execution_manager.py',transform_execution),('gui/flask_server.py',transform_gui)]:
        relative='fay-ue4/runtime/fay-local/app/'+rel;path=ROOT/relative
        old=path.read_text(encoding='utf-8-sig')
        if MARK in old:continue
        new=transform(old);ast.parse(new);prepared.append((relative,path,old,new))
    for relative,path,old,new in prepared:
        saved=BACKUP/relative;saved.parent.mkdir(parents=True,exist_ok=True)
        if not saved.exists():saved.write_text(old,encoding='utf-8')
        path.write_text(new,encoding='utf-8')
        changes.append(dict(path=relative,before_sha256=hashlib.sha256(saved.read_bytes()).hexdigest(),after_sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    if changes:(ROOT/'attendance-mcp/runtime/native-patches.json').write_text(json.dumps(changes,indent=2),encoding='utf-8')
    print(json.dumps({'patched':len(changes)}))

if __name__=='__main__':main()
