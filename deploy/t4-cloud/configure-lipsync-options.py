from pathlib import Path
import sys,shutil
folder=Path(sys.argv[1])
def patch(name,fn):
 p=folder/name;s=p.read_text(encoding='utf-8-sig');updated=fn(s)
 if updated!=s:
  backup=p.with_name(p.name+'.before-lipsync-settings')
  if not backup.exists():shutil.copy2(p,backup)
  p.write_text(updated,encoding='utf-8')
def settings(s):
 s=s.replace("DEFAULT=dict(revision=1,model=MODELS[0],", "LIPSYNC_MODELS=('wav2lip','musetalk')\nDEFAULT=dict(revision=1,lipsync_backend='wav2lip',model=MODELS[0],")
 s=s.replace("self.value=json.loads(self.path.read_text()) if self.path.exists() else dict(DEFAULT)","self.value={**DEFAULT,**json.loads(self.path.read_text())} if self.path.exists() else dict(DEFAULT)")
 a=s.index('    def update(self,data):');b=s.index('    def enabled(',a)
 s=s[:a]+'''    def validate(self,data):
        if not isinstance(data,dict):raise ValueError('设置必须为对象')
        data=dict(data)
        data.setdefault('lipsync_backend',self.value['lipsync_backend'])
        if set(data)!=FIELDS:raise ValueError('设置字段不完整或包含未知字段')
        if data['model'] not in MODELS:raise ValueError('Unsupported realtime model')
        if data['lipsync_backend'] not in LIPSYNC_MODELS:raise ValueError('不支持的唇动模型')
        if any(type(data[name]) is not bool for name in FIELDS-{'model','lipsync_backend'}):raise ValueError('开关必须为布尔值')
        return data
    def update(self,data):
        data=self.validate(data)
        previous=self.value
        self.value={**data,'revision':previous['revision']+1}
        try:self._save()
        except Exception:self.value=previous;raise
        return self.public()
''' +s[b:]
 return s
patch('capabilities.py',settings)
def gateway(s):
 s=s.replace('self.p=engine.Presenter(engine.options(self.id),self.gateway.assets,callback)','self.p=self.gateway.engine.Presenter(self.gateway.engine.options(self.id),self.gateway.assets,callback)')
 s=s.replace('self.assets=None;self.owner=None;', 'self.engine=engine;self.settings_lock=asyncio.Lock();self.assets=None;self.owner=None;')
 s=s.replace('self.loop=asyncio.get_running_loop();self.assets=await asyncio.to_thread(engine.Assets)',"self.loop=asyncio.get_running_loop();self.engine=self.lipsync_engine(self.settings.value['lipsync_backend']);self.assets=await asyncio.to_thread(self.engine.Assets)")
 s=s.replace("lipsync_backend='musetalk-1.5',lipsync_decoder='original',",'')
 s=s.replace("profile='presenter-v2-1080',", "profile='presenter-v2-1080',lipsync_backend=self.settings.value['lipsync_backend'],lipsync_decoder='original',")
 a=s.index('    async def settings_api(self,request):');b=s.index('    async def capabilities_api',a)
 s=s[:a]+'''    @staticmethod
    def lipsync_engine(backend):
        import importlib
        return importlib.import_module('musetalk_engine' if backend=='musetalk' else 'live_engine_v2')
    async def settings_api(self,request):
        if request.method=='POST':
            async with self.settings_lock:
                try:data=self.settings.validate(await request.json())
                except ValueError as error:raise web.HTTPBadRequest(text=str(error))
                changed=data['lipsync_backend']!=self.settings.value['lipsync_backend']
                next_engine=self.engine;next_assets=self.assets
                if changed:
                    next_engine=self.lipsync_engine(data['lipsync_backend'])
                    try:next_assets=await asyncio.to_thread(next_engine.Assets)
                    except Exception:
                        logging.exception('Lip-sync model load failed')
                        raise web.HTTPServiceUnavailable(text='唇动模型加载失败，原配置继续生效')
                self.settings.update(data)
                self.engine=next_engine;self.assets=next_assets
                owner=self.owner
                if owner:
                    await owner.stop_listening()
                    await owner.emit('settings_changed',settings=self.settings.public())
                    if changed:
                        await owner.close(code=4002)
                        if self.owner is owner:self.owner=None
        return web.json_response(self.settings.public())
''' +s[b:]
 return s
name='gateway_musetalk.py' if (folder/'gateway_musetalk.py').exists() else 'gateway.py'
patch(name,gateway)
def client(s):
 s=s.replace("$('#model-choice').value=config.model;","$('#model-choice').value=config.model;$('#lipsync-choice').value=config.lipsync_backend||'wav2lip';")
 s=s.replace("const value={model:$('#model-choice').value};", "const value={model:$('#model-choice').value,lipsync_backend:$('#lipsync-choice').value};")
 s=s.replace("$('#save-settings').onclick=async()=>{try{", "$('#save-settings').onclick=async()=>{$('#save-settings').disabled=true;$('#settings-message').textContent='正在保存并加载所选模型，请稍候…';try{")
 s=s.replace("catch(reason){$('#settings-message').textContent=reason.message;}};", "catch(reason){$('#settings-message').textContent=reason.message;}finally{$('#save-settings').disabled=false;}};")
 return s
patch('demo.js',client)
def html(s):
 marker='<label for="model-choice">实时语音模型</label>'
 s=s.replace(marker,'<label for="lipsync-choice">唇动模型</label><select id="lipsync-choice"><option value="wav2lip">Wav2Lip（响应更快）</option><option value="musetalk">MuseTalk 1.5（原版，T4 上播放较慢）</option></select><p class="muted">切换唇动模型后会自动重新连接音视频，首次加载需要稍等。</p>'+marker)
 import re
 s=re.sub(r'/demo.js\?v=[^"\s]+','/demo.js?v=20261111-lipsync-settings1',s)
 return s
patch('index.html',html)
print('PATCHED',folder)
