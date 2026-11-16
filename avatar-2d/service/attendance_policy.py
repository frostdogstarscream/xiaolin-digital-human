"""Avatar-only MCP intent guidance and once-per-turn execution receipts.

All natural-language intent decisions stay with the existing LLM request.
Python guards only availability, turn identity, actual results and repeat calls.
"""
import json
import threading
import time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]/'attendance-mcp'
MARKER=ROOT/'runtime/registration.json'
TOOL='attendance_check_in'
LOCK=threading.RLock()
ATTEMPTS={}

def installed():return MARKER.is_file()

def available():
    try:
        marker=json.loads(MARKER.read_text(encoding='utf-8'))
        from faymcp import runtime_bridge
        return bool(marker.get('enabled') and any(t.get('name')==TOOL and t.get('server_id')==marker['server_id']
            for t in runtime_bridge.get_enabled_tools()))
    except Exception:return False

def receipt(username,cid):
    with LOCK:
        for value in reversed(list(ATTEMPTS.values())):
            if value['username']==username and value['conversation_id']==cid:return dict(value)
    return None

def semantic_instruction(username,cid,judge=False):
    if username!='Avatar2D' or not installed():return ''
    result=receipt(username,cid)
    status='available' if available() else 'unavailable'
    proof='success' if result and result.get('success') else 'failed' if result and result.get('done') else 'not_executed'
    return ('\n【MCP语义执行与真实结果规则，优先于宽泛的闲聊/知识检索示例】'
        '\n当前唯一占位考勤工具 attendance_check_in，无参数，只做测试，不接真实考勤。'
        '工具可用性='+status+'；本轮服务端执行凭据='+proof+'。'
        '\n按当前输入及上下文识别真实执行意图。明确要求打卡、上班签到、请你代办签到，或确认上一轮明确的打卡提议，才执行。'
        '不要求固定措辞；“帮我签到”“我想做个上班签到”均可。'
        '上一句如果在询问是否打卡，“好的”“帮我办一下”可表示确认；无相关上下文的“好的”按普通回应。'
        '\n否定、不需要、已打过卡的陈述、打卡含义咨询、引用例句、旅游或咖啡店打卡均不执行。'
        '“我到公司了”等陈述不等于授权，先问是否需要占位打卡测试；询问今天是否打过卡属于查询，当前没有记录查询能力。'
        '\n只有真实凭据 success 才能说“占位打卡测试成功”，说明这是测试；不能声称真实考勤已记录。'
        '无执行凭据时不得声称已完成；工具不可用时说明暂不可用、没有执行。'
        + ('\n意图明确且工具available才 action=tool，gesture=idle；其它情况 action=finish，message正常回答或澄清。'
           '概念、否定、探店话题都可直接回答，不因出现工具相关词而调用。拿不准先澄清，禁止以不确定为由执行。' if judge else ''))

def is_attendance_state(state):
    return bool(state.username=='Avatar2D' and installed() and
        (set(state.tool_registry)=={TOOL} or (state.first_plan or {}).get('name')==TOOL))

def invoke_once(state,spec,args,attempt):
    if state.username!='Avatar2D' or spec.name!=TOOL or not installed():return spec.executor(args,attempt)
    import gesture_planner as gestures
    signal=gestures.signal(state.username,state.conversation_id)
    if state.cancel_flag or not signal:return False,None,'旧轮次已取消，未执行占位打卡。'
    if args:return False,None,'占位打卡工具不接受参数，未执行。'
    key=(signal['controller_id'],signal['turn_id'])
    with LOCK:
        if key in ATTEMPTS:
            previous=ATTEMPTS[key]
            return (previous.get('success',False),previous.get('output'),previous.get('error') or
                    (None if previous.get('success') else '本轮调用已开始，不重复执行。'))
        record=dict(username=state.username,conversation_id=state.conversation_id,turn_id=signal['turn_id'],
                    started=time.time(),done=False,success=False)
        ATTEMPTS[key]=record
    if not gestures.is_current(state.username,state.conversation_id):
        success,output,error=False,None,'旧轮次已取消，未执行占位打卡。'
    else:
        try:success,output,error=spec.executor(args,attempt)
        except Exception as exc:success,output,error=False,None,'MCP 调用失败：'+type(exc).__name__
    if success and str(output).strip()!='success':
        success,output,error=False,None,'MCP 未返回预期的 success，未确认执行成功。'
    with LOCK:
        record.update(done=True,success=bool(success),output=output if success else None,error=error,ended=time.time())
        (ROOT/'runtime').mkdir(parents=True,exist_ok=True)
        with (ROOT/'runtime/dispatch.jsonl').open('a',encoding='utf-8') as out:out.write(json.dumps(record,ensure_ascii=False)+'\n')
        if len(ATTEMPTS)>256:
            for old in list(ATTEMPTS)[:-128]:
                if ATTEMPTS[old].get('done'):ATTEMPTS.pop(old,None)
    return bool(success),output if success else None,error

def cancel_turn(username):
    if username!='Avatar2D' or not installed():return
    from llm.execution_manager import get_execution_manager
    manager=get_execution_manager();state=manager.get_state(username)
    if state and is_attendance_state(state):
        manager.cancel(username);manager.consume_result(username)
