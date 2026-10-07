import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile,readdir} from 'node:fs/promises';
import {createSubscriptionHandler,BrevoProvider,renderEmail,deliverEdition,validateEmailEdition} from '../../scripts/newsletter/email-service.mjs';
const issue=JSON.parse(await readFile(new URL('../../daily/data/issues/2026-10-04.json',import.meta.url),'utf8'));
const origin='https://eaglhuang.github.io';
const site=origin+'/AI-learning-notes';
const request=(body,extra={})=>new Request('https://api.test/subscribe',{method:'POST',headers:{Origin:origin,'Content-Type':'application/json',...extra},body:JSON.stringify(body)});
const valid={email:'reader@example.com',locale:'zh-TW',consent:true,website:''};
test('all stored editions satisfy the email contract for their own publication date',async()=>{
  const directory=new URL('../../daily/data/issues/',import.meta.url);
  for(const name of (await readdir(directory)).filter(name=>name.endsWith('.json'))){
    const stored=JSON.parse(await readFile(new URL(name,directory),'utf8'));
    assert.deepEqual(validateEmailEdition(stored),[],name);
    for(const locale of ['zh-TW','en']){
      const email=renderEmail(stored,locale,site);
      for(const item of stored.items)assert.ok(email.text.includes(item[locale].summary));
    }
  }
});
test('new summary length policy preserves old editions and counts Unicode consistently',()=>{
  assert.deepEqual(validateEmailEdition(issue),[]);
  const next=structuredClone(issue);next.date='2026-10-06';next.reviewed_on='2026-10-06';
  assert.ok(validateEmailEdition(next).some(e=>e.includes('180–240')));
  for(const item of next.items)item['zh-TW'].summary='測'.repeat(200);
  assert.deepEqual(validateEmailEdition(next),[]);
  for(const length of [179,241]){next.items[0]['zh-TW'].summary='測'.repeat(length);assert.ok(validateEmailEdition(next).some(e=>e.includes('180–240')));}
  for(const length of [180,240]){next.items[0]['zh-TW'].summary='測'.repeat(length);assert.deepEqual(validateEmailEdition(next),[]);}
  next.items[0]['zh-TW'].summary='測'.repeat(179)+' \n\t\u0085\u3000'.repeat(8);
  assert.ok(validateEmailEdition(next).some(e=>e.includes('180–240')));
  next.items[0]['zh-TW'].summary='測'.repeat(179)+'𠮷';assert.deepEqual(validateEmailEdition(next),[]);
  assert.ok(renderEmail(next,'zh-TW',site).html.includes(next.items[0]['zh-TW'].summary));
});
test('unconfigured service fails closed',async()=>{const response=await createSubscriptionHandler()(request(valid));assert.equal(response.status,503);});
test('dated 500-character policy matches shared Unicode fixtures without changing English',async()=>{
  const cases=JSON.parse(await readFile(new URL('./fixtures/summary-policies.json',import.meta.url),'utf8'));
  for(const c of cases){
    const next=structuredClone(issue);next.date=c.date;next.reviewed_on=c.date;
    for(const item of next.items)item['zh-TW'].summary='測'.repeat(c.characters)+c.tail;
    assert.equal(validateEmailEdition(next).length===0,c.valid,JSON.stringify(c));
  }
  const next=structuredClone(issue);next.date='2026-10-07';next.reviewed_on=next.date;
  for(const item of next.items)item['zh-TW'].summary='測'.repeat(500);
  assert.deepEqual(validateEmailEdition(next),[]);
  assert.ok(renderEmail(next,'zh-TW',site).html.includes('測'.repeat(500)));
  assert.equal(next.items[0].en.summary,issue.items[0].en.summary);
});
test('requires origin, valid email, consent and rate limiter',async()=>{let calls=0;const handler=createSubscriptionHandler({origin,provider:{requestDoubleOptIn:async()=>calls++},rateLimiter:{allow:async()=>true}});for(const body of [{...valid,consent:false},{...valid,email:'bad'},{...valid,locale:'xx'},{...valid,website:'bot'}])assert.equal((await handler(request(body))).status,400);assert.equal((await handler(request(valid,{Origin:'https://evil.test'}))).status,403);assert.equal(calls,0);});
test('acceptance means confirmation requested, never subscribed',async()=>{let body;const handler=createSubscriptionHandler({origin,provider:{requestDoubleOptIn:async b=>{body=b;}},rateLimiter:{allow:async()=>true}});const response=await handler(request(valid));assert.equal(response.status,202);assert.deepEqual(await response.json(),{status:'confirmation_requested'});assert.deepEqual(body,{email:valid.email,locale:valid.locale});assert.equal(response.headers.get('Access-Control-Allow-Origin'),origin);});
test('provider outage, rate limit and body limit fail honestly',async()=>{for(const [limiter,provider,status] of [[false,false,429],[true,true,503]]){const handler=createSubscriptionHandler({origin,provider:{requestDoubleOptIn:async()=>{if(provider)throw Error('private details');}},rateLimiter:{allow:async()=>limiter}});const response=await handler(request(valid));assert.equal(response.status,status);assert.ok(!(await response.text()).includes('private'));}const handler=createSubscriptionHandler({origin,provider:{},rateLimiter:{}});assert.equal((await handler(request({...valid,extra:'x'.repeat(3000)}))).status,413);});
test('Brevo uses double opt-in API with server secret and language list only',async()=>{let seen;const provider=new BrevoProvider({apiKey:'test-not-a-secret',templateIds:{'zh-TW':1,en:2},listIds:{'zh-TW':3,en:4},redirectUrl:site+'/daily/'},async(url,options)=>{seen={url,options};return new Response(null,{status:204});});await provider.requestDoubleOptIn({email:valid.email,locale:'en'});assert.equal(seen.url,'https://api.brevo.com/v3/contacts/doubleOptinConfirmation');assert.deepEqual(JSON.parse(seen.options.body).includeListIds,[4]);assert.equal(JSON.parse(seen.options.body).templateId,2);assert.ok(!JSON.parse(seen.options.body).updateEnabled);});
test('email preview escapes content and has full edition link and provider footer',()=>{const altered=structuredClone(issue);altered.items[0].en.title='<img src=x onerror=alert(1)>';const email=renderEmail(altered,'en',site);assert.ok(email.html.includes('&lt;img'));assert.ok(!email.html.includes('<img src=x'));assert.ok(email.html.includes('<!--PROVIDER_FOOTER-->'));assert.ok(email.text.includes('/daily/2026-10-04/en/'));});
test('delivery defaults to local preview without provider side effects',async()=>{const result=await deliverEdition({issue,locale:'en',siteUrl:site});assert.equal(result.status,'preview');assert.ok(result.digest);});
test('email enforces shared production edition contract',()=>{assert.deepEqual(validateEmailEdition(issue),[]);for(const mutate of [i=>i.date='2099-99-99',i=>i.items=i.items.slice(0,1),i=>delete i.reviewed_on,i=>delete i.items[0]['zh-TW'],i=>i.items[0].source_url='javascript:alert(1)',i=>i.items[1].id=i.items[0].id]){const changed=structuredClone(issue);mutate(changed);assert.ok(validateEmailEdition(changed).length);assert.throws(()=>renderEmail(changed,'en',site));}});
test('canonical URL is escaped even for hostile configuration',()=>{const email=renderEmail(issue,'en','https://example.com/\" data-injected=\"yes');assert.ok(!email.html.includes('href="https://example.com/" data-injected='));assert.ok(email.html.includes('&quot;'));});
test('delivery is approved, capacity bounded, durable and idempotent',async()=>{const preview=await deliverEdition({issue,locale:'en',siteUrl:site});let claimed=false,sends=0;const states=[];const args={issue,locale:'en',siteUrl:site,approval:{date:issue.date,locale:'en',digest:preview.digest},recipientCount:10,maxRecipients:20,provider:{createCampaign:async()=>7,sendCampaign:async()=>sends++},ledger:{claim:async()=>{if(claimed)return false;claimed=true;return true;},update:async(key,value)=>states.push(value.state)}};assert.equal((await deliverEdition(args)).status,'accepted');assert.equal((await deliverEdition(args)).status,'already_reserved');assert.equal(sends,1);assert.deepEqual(states,['send_requested','accepted']);await assert.rejects(()=>deliverEdition({...args,recipientCount:30}));});
test('ambiguous send remains reserved and is never auto-retried',async()=>{const preview=await deliverEdition({issue,locale:'en',siteUrl:site});let reserved=false,send=0,last;const args={issue,locale:'en',siteUrl:site,approval:{date:issue.date,locale:'en',digest:preview.digest},recipientCount:1,maxRecipients:2,provider:{createCampaign:async()=>8,sendCampaign:async()=>{send++;throw Error('network');}},ledger:{claim:async()=>{if(reserved)return false;reserved=true;return true;},update:async(k,v)=>{last=v.state;}}};await assert.rejects(()=>deliverEdition(args),/uncertain/);assert.equal(last,'uncertain');assert.equal((await deliverEdition(args)).status,'already_reserved');assert.equal(send,1);});
