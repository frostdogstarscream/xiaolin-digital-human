async page=>{
  const results={scope:'paid embedding/rerank through real browser, isolated acceptance namespace',cases:[]};
  async function ask(text){
    await page.evaluate(()=>{qwenDemo.events=[];});await page.getByRole('textbox',{name:'输入问题'}).fill(text);await page.getByRole('button',{name:'发送',exact:true}).click();
    await page.waitForFunction(()=>qwenDemo.events.some(e=>e.type==='playback_done')||qwenDemo.events.some(e=>e.type==='error'),null,{timeout:45000});
    return page.evaluate(()=>{const e=qwenDemo.events;if(e.some(x=>x.type==='error'))throw Error(JSON.stringify(e.filter(x=>x.type==='error')));return {answer:e.filter(x=>x.type==='assistant_text').at(-1)?.text,result:e.find(x=>x.type==='capability_result')?.result};});
  }
  await page.getByRole('button',{name:'知识与记录',exact:true}).click();
  await page.getByRole('textbox',{name:'资料标题'}).fill('验收资料-小霖试验展厅');
  await page.getByRole('textbox',{name:'资料正文'}).fill('这是隔离命名空间的验收资料，不是真实业务资料。小霖试验展厅的开放时间为每周二至周日09:30至16:30，周一闭馆。该试验展厅的服务台编号为R726。');
  await page.getByRole('button',{name:'入库资料',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('#knowledge-message').textContent.includes('已入库'),null,{timeout:30000});
  const docIds=await page.evaluate(()=>qwenDemo.capabilities.knowledge_documents.map(x=>x.id));
  await page.getByRole('button',{name:'对话',exact:true}).click();
  const knowledge=await ask('请查业务知识库，小霖试验展厅周一是否开放，服务台编号是什么？');
  if(!knowledge.result?.knowledge?.matches?.length||knowledge.result.knowledge.rerank_calls!==1||!knowledge.answer?.includes('闭馆'))throw Error('Real knowledge retrieval missing '+JSON.stringify(knowledge));
  results.cases.push({name:'business_knowledge',...knowledge});
  const before=await page.evaluate(async()=>((await api('/api/capabilities')).counts.memory||0));
  const remember=await ask('请记住，我最喜欢喝龙井茶，我的验收代号是蓝鹊七二。');
  const deadline=Date.now()+15000;let after;
  while(true){after=await page.evaluate(async()=>((await api('/api/capabilities')).counts.memory||0));if(after>before)break;if(Date.now()>deadline)throw Error('Memory was not persisted');await page.waitForTimeout(150);}
  results.cases.push({name:'persist_completed_memory',before,after,...remember});
  await page.getByRole('button',{name:'停止对话',exact:true}).click();await page.waitForFunction(()=>!qwenDemo.provider,null,{timeout:10000});
  const recall=await ask('请检索关联记忆，我之前说喜欢喝什么茶，验收代号是什么？');
  if(!recall.result?.memory?.matches?.length||recall.result.memory.rerank_calls!==1||!recall.answer?.includes('龙井')||!recall.answer?.includes('蓝鹊'))throw Error('Cross-model-session memory recall failed '+JSON.stringify(recall));
  results.cases.push({name:'recall_after_model_reconnect',...recall});
  results.models=await page.evaluate(async()=>{const d=await api('/api/capabilities');return {embedding:d.embedding_model,rerank:d.rerank_model,namespace:d.namespace};});
  for(const id of docIds)await page.evaluate(id=>api('/api/knowledge/'+id,{method:'DELETE'}),id);
  results.testKnowledgeRemoved=true;results.status='PASSED';return results;
}
