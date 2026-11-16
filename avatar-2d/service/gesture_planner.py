"""Streaming reply gestures, isolated native turn metadata, and one-motion scheduling."""
import copy
import json
import threading
import time
import uuid

GESTURES=frozenset(('idle','welcome-wave','goodbye-wave','acknowledge-nod','explain-open-palms'))
STAMP_LOCK=threading.Lock()
LAST_STAMP=0

def next_stamp():
    global LAST_STAMP
    with STAMP_LOCK:
        LAST_STAMP=max(time.time_ns(),LAST_STAMP+1)
        return LAST_STAMP


class GestureDecoder:
    """Decode one top-level JSON object incrementally; only release its reply string.

    Prefix fields are bounded. Strings use JSONDecoder so escapes and surrogate
    pairs remain valid even when a provider splits a stream between characters.
    Plain replies remain compatible; JSON control fields are never spoken.
    """
    def __init__(self,text_key='text',on_gesture=None,on_text_start=None):
        self.text_key=text_key;self.on_gesture=on_gesture or (lambda value:None)
        self.on_text_start=on_text_start or (lambda:None)
        self.buffer='';self.pos=0;self.state='start';self.key=None;self.fields={}
        self.reply='';self.raw_string='"';self.emitted=0;self.plain=False;self.gesture_seen=False
        self.json=json.JSONDecoder();self.prefix_count=0;self.text_started=False

    def _gesture(self,value):
        if not self.gesture_seen:
            self.fields['gesture']=value if isinstance(value,str) and value in GESTURES else 'idle'
            self.gesture_seen=True;self.on_gesture(self.fields['gesture'])

    def feed(self,text):
        if not text:return ''
        if self.plain:self.reply+=text;return text
        self.buffer+=text;output=[]
        while True:
            if self.state=='reply':
                # Decode newly available JSON string prefix without inventing closing escapes.
                while self.pos<len(self.buffer):
                    ch=self.buffer[self.pos];self.pos+=1;self.raw_string+=ch
                    try:
                        decoded,end=self.json.raw_decode(self.raw_string)
                        complete=True
                    except json.JSONDecodeError:
                        complete=False
                        try:decoded=json.loads(self.raw_string+'"')
                        except json.JSONDecodeError:continue
                    if isinstance(decoded,str):
                        # Hold a dangling high surrogate until its pair arrives.
                        safe=decoded[:-1] if decoded and 0xD800<=ord(decoded[-1])<=0xDBFF else decoded
                        delta=safe[self.emitted:]
                        if delta:output.append(delta);self.reply+=delta;self.emitted=len(safe)
                    if complete:self.state='done';break
                break
            if self.state=='done':break
            while self.pos<len(self.buffer) and self.buffer[self.pos].isspace():self.pos+=1
            if self.pos>=len(self.buffer):break
            if self.state=='start':
                if self.buffer[self.pos]=='`':
                    newline=self.buffer.find('\n',self.pos)
                    if newline<0:
                        if len(self.buffer)>512:self.state='done'
                        break
                    self.pos=newline+1;continue
                if self.buffer[self.pos]!='{':
                    self._gesture('idle');self.plain=True
                    delta=self.buffer[self.pos:];self.reply+=delta;output.append(delta);self.buffer='';break
                self.pos+=1;self.state='key';continue
            if self.state=='key':
                if self.buffer[self.pos] in ',}':
                    if self.buffer[self.pos]=='}':self.state='done';break
                    self.pos+=1;continue
                try:key,end=self.json.raw_decode(self.buffer,self.pos)
                except json.JSONDecodeError:break
                if not isinstance(key,str):self.state='done';break
                self.key=key;self.pos=end;self.state='colon';continue
            if self.state=='colon':
                if self.buffer[self.pos]!=':':self.state='done';break
                self.pos+=1;self.state='value';continue
            if self.state=='value':
                if self.key==self.text_key:
                    if self.buffer[self.pos]!='"':self.state='done';break
                    self._gesture(self.fields.get('gesture','idle'))
                    self.text_started=True;self.on_text_start()
                    self.pos+=1;self.state='reply';continue
                try:value,end=self.json.raw_decode(self.buffer,self.pos)
                except json.JSONDecodeError:break
                self.fields[self.key]=value
                if self.key=='gesture':self._gesture(value if isinstance(value,str) else 'idle')
                self.pos=end;self.state='key'
            if not self.text_started and self.pos>512:self.state='done';break
        if not self.text_started and len(self.buffer)>1024:self.state='done'
        return ''.join(output)

    def finish(self):
        self._gesture('idle')
        if not self.reply.strip():raise ValueError('No recoverable reply text')
        return self.reply


class ActionController:
    def __init__(self,clock=time.monotonic):
        self.clock=clock;self.controller_id=uuid.uuid4().hex;self.last_input=None
        self.welcomed=False;self.closed=False;self.last_played={};self.turn=None;self.active_motion=None

    def begin(self,epoch):
        now=self.clock()
        if self.closed or self.last_input is None or now-self.last_input>=60:
            self.welcomed=False;self.closed=False
        self.last_input=now
        self.turn=dict(turn_id=uuid.uuid4().hex,epoch=epoch,issued_at=next_stamp(),reserved=None,consumed=False)
        return self.turn

    def context(self,epoch,fixed=False):
        if self.turn is None:self.begin(epoch)
        self.turn['epoch']=epoch
        return dict(controller_id=self.controller_id,turn_id=self.turn['turn_id'],epoch=epoch,
            issued_at=self.turn['issued_at'],welcome_allowed=not self.welcomed,
            motion_available=not bool(self.turn['reserved'] or self.turn['consumed']),
            cooldown_remaining={g:round(max(0,15-(self.clock()-t)),2) for g,t in self.last_played.items()},
            recent_actions=[{'gesture':g,'seconds_ago':round(self.clock()-t,2)} for g,t in self.last_played.items()],
            fixed_gesture='welcome-wave' if fixed else None)

    def current(self,signal,epoch):
        return bool(self.turn and isinstance(signal,dict) and signal.get('controller_id')==self.controller_id
                    and signal.get('turn_id')==self.turn['turn_id'] and signal.get('epoch')==epoch)

    def reserve(self,signal,epoch):
        if not self.current(signal,epoch):raise ValueError('Stale or unbound gesture turn')
        gesture=signal.get('gesture','idle')
        if not isinstance(gesture,str) or gesture not in GESTURES or gesture=='idle':return 'idle'
        if self.turn['reserved'] or self.turn['consumed']:return 'idle'
        if gesture=='welcome-wave' and self.welcomed:return 'idle'
        if self.clock()-self.last_played.get(gesture,-1e10)<15:return 'idle'
        self.turn['reserved']=signal.get('plan_id');return gesture

    def started(self,info):
        if not self.current(info,info.get('epoch')) or self.turn['reserved']!=info.get('plan_id'):return False
        gesture=info.get('motion_start')
        if not isinstance(gesture,str) or gesture not in GESTURES or gesture=='idle' or self.turn['consumed']:return False
        self.turn['consumed']=True;self.last_played[gesture]=self.clock();self.active_motion=gesture
        if gesture=='welcome-wave':self.welcomed=True
        if gesture=='goodbye-wave':self.closed=True
        return True

    def cancel(self):self.turn=None;self.active_motion=None


LOCK=threading.RLock()
RECORDS={}
CURRENT={}
WATERMARK={}


def register_request(username,conversation_id,context,request=''):
    if username!='Avatar2D':return True
    if not conversation_id or not isinstance(context,dict):
        return False
    if not isinstance(context.get('turn_id'),str) or type(context.get('epoch')) is not int:return False
    with LOCK:
        stamp=(context.get('issued_at',0),context['epoch'])
        if stamp<=WATERMARK.get(username,(0,0)):return False
        WATERMARK[username]=stamp
        record=dict(control=copy.deepcopy(context),gesture='idle',plan_id=uuid.uuid4().hex,request=request)
        if context.get('fixed_gesture')=='welcome-wave':record['gesture']='welcome-wave'
        RECORDS[(username,conversation_id)]=record;CURRENT[username]=(username,conversation_id)
        if len(RECORDS)>128:
            for key in list(RECORDS)[:-64]:
                if key not in CURRENT.values():RECORDS.pop(key,None)
        return True


def invalidate(username):
    with LOCK:CURRENT.pop(username,None)


def is_current(username,conversation_id):
    with LOCK:return username!='Avatar2D' or CURRENT.get(username)==(username,conversation_id)


def signal(username,conversation_id):
    with LOCK:
        if not is_current(username,conversation_id):return None
        record=RECORDS.get((username,conversation_id))
        if not record:return None
        control=record['control']
        return {k:control[k] for k in ('controller_id','turn_id','epoch','issued_at')} | dict(
            gesture=record['gesture'],plan_id=record['plan_id'],conversation_id=conversation_id)


def select(username,conversation_id,gesture,timing=None):
    with LOCK:
        if not is_current(username,conversation_id):return
        record=RECORDS.get((username,conversation_id))
        if not record:return
        record['gesture']=gesture if gesture in GESTURES else 'idle';record['plan_id']=uuid.uuid4().hex
    if timing:timing.mark('gesture_decided',gesture=record['gesture'])

def fail(username,conversation_id):
    with LOCK:
        record=RECORDS.get((username,conversation_id))
        if record and is_current(username,conversation_id):record['error']=True

def failed(username,conversation_id):
    with LOCK:return bool(username=='Avatar2D' and RECORDS.get((username,conversation_id),{}).get('error'))


def instruction(username,conversation_id,judge=False):
    with LOCK:record=copy.deepcopy(RECORDS.get((username,conversation_id),{}))
    control=record.get('control',{})
    state={k:control.get(k) for k in ('welcome_allowed','motion_available','cooldown_remaining','recent_actions')}
    schema='{"action":"finish","gesture":"idle","message":"回复正文"}' if judge else '{"gesture":"idle","text":"回复正文"}'
    current_request=str(record.get('request') or '').strip()
    from attendance_policy import semantic_instruction
    return ('\n\n【数字人自动动作协议，必须遵守】\n'
        '只输出一个JSON对象，不加代码围栏。动作字段必须先于回复正文，正文可连续生成。格式：'+schema+'。'
        'gesture只能为idle、welcome-wave、goodbye-wave、acknowledge-nod、explain-open-palms。'
        '欢迎只用于真实首次接待；告别只用于用户明确结束交流，引用“再见”、询问词义不能告别；'
        '点头只用于主要表达同意或收到，否定/纠正不用点头。含两个以上实质要点、预计讲解超过约5秒的介绍、解释、建议、总结优先摊手。'
        '普通简短应答（如20字以内的事实短答）优先idle；确认收到可点头。当前素材挥手7秒、点头4秒、摊手9秒，不要强行为每轮安排动作。'
        '用户要求不要动作或无法确定时用idle。motion_available为false才表示本轮所有动作名额已用。'
        'welcome_allowed为false仅禁止welcome-wave，仍可点头、摊手或告别。'
        'cooldown_remaining仅禁止剩余秒数大于0的对应动作，不禁止其它动作；最近做过不同动作也不占用当前新轮次的名额。'
        '状态：'+json.dumps(state,ensure_ascii=False)+'。'
        +('本轮最新用户输入（JSON字符串）：'+json.dumps(current_request,ensure_ascii=False)+
          '。这是本轮唯一待回答问题，优先于历史中被打断、未完成的旧问题。请回答此新输入，不要续写旧问题的答案。' if current_request else '')
        +('需要工具时仍使用原来的action=tool结构，gesture必须为idle；不要把工具决策字段改名。' if judge else '')
        +semantic_instruction(username,conversation_id,judge))


def _messages(messages,extra):
    from langchain_core.messages import SystemMessage
    return [*messages,SystemMessage(content=extra)]

def model_stream(llm,messages):
    # Disable SDK retries on this user-facing path; one request remains one request.
    model=llm.factory('small',streaming=True) if hasattr(llm,'factory') else llm
    if getattr(model,'root_client',None) is not None:
        model.client=model.root_client.with_options(max_retries=0).chat.completions
    yield from model.stream(messages)


def reply_stream(llm,messages,username,conversation_id,timing=None):
    if username!='Avatar2D':
        yield from llm.stream(messages);return
    if not is_current(username,conversation_id):return
    decoder=GestureDecoder(on_gesture=lambda g:select(username,conversation_id,g,timing))
    if timing:timing.mark('gesture_protocol_enabled',user_facing_model_requests=1,independent_gesture_requests=0)
    for chunk in model_stream(llm,_messages(messages,instruction(username,conversation_id))):
        if not is_current(username,conversation_id):return
        if timing:timing.mark('llm_first_event')
        raw=chunk if isinstance(chunk,str) else getattr(chunk,'content','')
        if not isinstance(raw,str):continue
        text=decoder.feed(raw)
        if text:yield text
    try:decoder.finish()
    except ValueError:
        fail(username,conversation_id);raise


def judge_decision(llm,messages,username,conversation_id,callback,on_tool=None,timing=None):
    """Avatar-only judge path: preserve tool JSON, stream decoded finish text."""
    if not is_current(username,conversation_id):return {'action':'finish','message':'','_streamed':True}
    decoder=GestureDecoder(text_key='message');raw_parts=[];reported=False;tool=False
    if timing:timing.mark('gesture_protocol_enabled',user_facing_model_requests=1,independent_gesture_requests=0)
    for chunk in model_stream(llm,_messages(messages,instruction(username,conversation_id,judge=True))):
        if not is_current(username,conversation_id):return {'action':'finish','message':'','_streamed':True}
        if timing:timing.mark('llm_first_event')
        raw=chunk if isinstance(chunk,str) else getattr(chunk,'content','')
        if not isinstance(raw,str):continue
        raw_parts.append(raw);text=decoder.feed(raw)
        action=decoder.fields.get('action')
        if action=='tool' and not tool:
            tool=True;select(username,conversation_id,'idle',timing)
            if timing:timing.mark('decision_available',decision='tool')
            if on_tool:on_tool()
        if decoder.gesture_seen and not reported:
            select(username,conversation_id,decoder.fields['gesture'] if action=='finish' else 'idle',timing);reported=True
        if text and not tool:
            if timing:timing.mark('llm_first_text');timing.mark('reply_first_text')
            callback(text)
    if timing:timing.mark('llm_stream_done')
    if tool:
        source=''.join(raw_parts).strip()
        if source.startswith('```'):source=source.split('\n',1)[1].rsplit('```',1)[0].strip()
        decision=json.loads(source)
        decision['_tool_early_streamed']=bool(on_tool);return decision
    try:decoder.finish()
    except ValueError:
        fail(username,conversation_id);raise
    return {'action':'finish','message':decoder.reply,'_streamed':True}
