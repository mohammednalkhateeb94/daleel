import json, csv
D='eval/results_heldout_v1.0'
gold=[json.loads(l) for l in open('eval/cases_heldout.jsonl',encoding='utf-8')]
G={g['id']:g for g in gold}
SYS=[('daleel','«دليل» v1.0',f'{D}/run1_cases.json'),('bm25','البحث بالكلمات (BM25)',f'{D}/baselines_run1_cases_bm25.json'),
     ('general','نموذج عام يرى المكتبة',f'{D}/baselines_run1_cases_general.json'),('general_pre','النموذج العام بعد الفحص بالقواعد',f'{D}/baselines_run1_cases_general_pre.json')]
OUT={k:{c['id']:c for c in json.load(open(p,encoding='utf-8'))['cases']} for k,_,p in SYS}
segs={s['id']:s for s in json.load(open('data/segments.json',encoding='utf-8'))['segments']}
tpl=json.load(open('data/templates.json',encoding='utf-8'))
T=lambda k:(tpl[k] if isinstance(tpl[k],str) else tpl[k].get('text',''))
REASON_TPL={"verse_not_found":"ام-06","not_covered":"ام-07","tafsir":"ام-09","off_topic":"ام-01","fatwa":"ام-02"}
REASON_DESC={
 "tafsir":"صُنّف السؤال طلبَ تفسير لآية أو لفظ قرآني بعينه؛ يُعرض قالب امتناع يحيل إلى مصدر تفسير.",
 "fatwa":"صُنّف السؤال طلبَ حكم شرعي أو حالةً شخصية؛ يُعرض قالب إحالة إلى أهل العلم.",
 "off_topic":"صُنّف السؤال خارج موضوع التعريف بالقرآن.",
 "verse_not_found":"قرأ الفحص بالقواعد السؤال على أنه نص آية للبحث عنه، ولم يجد آية مطابقة.",
 "not_covered":"لم يُعرض مقطع لأن المكتبة لا تحتوي ما يجيب (قرار الموجّه أو إحدى البوابات)."}
GATE_DESC={"blocked":"بوابة القواعد: الموجّه اقترح استيضاحاً بين حاجات أو مقطعاً، ولم يبقَ بعد الفحص خياران مغطّيان أو مقطع صالح، فكان القرار امتناعاً.",
 "near_miss":"المطابقة السلبية: السؤال من جنس «أسئلة قريبة لا يجيب عنها» المسجلة للمقطع.",
 "need_mismatch":"المقطع من حاجة غير الحاجة التي يسأل عنها المستخدم.","verify":"فحص نص المقطع حكم بأنه لا يجيب."}
TURNS={'H11':['H11-T1','H11-T2'],'H12':['H12-T1','H12-T2']}
PRIMARY=[f"H{i:02d}" for i in range(1,16)]; SUPP=['HX01','HX02','HX03']

def shown_text(sysk,c):
    """ما ظهر فعلاً للمستخدم كما تسمح به المخرجات المحفوظة."""
    if c['got']=='verse': return "عُرض نص آية من المصحف (قالب «هذا نص الآية كما في المصحف»). نص الآية المعروضة لم يُحفظ في مخرجات القياس."
    if c['got']=='abstain':
        if sysk in('daleel','bm25','general_pre') and c.get('reason') in REASON_TPL: return f"قالب {REASON_TPL[c['reason']]}: «{T(REASON_TPL[c['reason']])}»"
        return "امتناع."
    if c['got']=='clarify': return "سؤال استيضاح بين حاجتين (نص الخيارات لم يُحفظ)."
    if c['got']=='answer':
        if sysk=='daleel':
            parts=[]
            for f in c.get('focus') or []:
                parts.append(f"{f['id']}: " + (f"الجمل المختارة: «{f['excerpt'].replace(chr(10),' ⏎ ')}» (وبقية النص خلف «أريد التفصيل»)" if f.get('excerpt') else "نص المقطع كاملاً (انظر الملحق ب)"))
            return " | ".join(parts)
        if sysk=='bm25': return "عرض المقطع "+"، ".join(c['segs'])+" كما في المكتبة (انظر الملحق ب)."
        if sysk=='general': return "جواب مكتوب من النموذج يستشهد بـ "+"، ".join(c['segs'])+(f". أول 600 حرف من الردّ الأول: «{c['text'].replace(chr(10),' ⏎ ')}»" if c.get('text') else '')
        return "جواب مكتوب من النموذج يستشهد بـ "+"، ".join(c['segs'])+" (نص الردّ لم يُحفظ)."
    if c['got']=='free_answer':
        return "جواب مكتوب من النموذج بلا استشهاد بأي مقطع وبلا عبارة امتناع"+(f". أول 600 حرف من الردّ الأول: «{c['text'].replace(chr(10),' ⏎ ')}»" if sysk=='general' and c.get('text') else " (نص الردّ لم يُحفظ).")
    return c['got']

def rec(sysk,c):
    g=G[c['id']]
    r={"canonical_decision":c['canonical'],"raw_type":c['got'],"segments_shown":c['segs'],"forbidden_shown":c['forbidden_shown'],
       "pass":c['ok'],"decision_ok":c['decision_ok'],"selection_ok":c['selection_ok'],"inappropriate":c['inappropriate'],
       "answered_when_should_abstain":c['unsafe'],"free_answer_when_should_abstain":c['got']=='free_answer' and g['decision'] in('NOT_COVERED','REFER'),
       "error_category":c.get('failure'),"what_appeared":shown_text(sysk,c)}
    if sysk=='daleel':
        m=c.get('method') or {}
        r.update(reason_code=c.get('reason'),gate=c.get('gate'),router_task=m.get('task'),router_issue=m.get('issue'),router_sensitivity=m.get('sensitivity'))
    if c['id'].endswith('-T2'): r['first_turn_segments_shown']=c.get('shown1')
    if sysk=='general_pre' and c['id']=='H12-T2': r['note']="قيد تنفيذ معروف: التقط الفحص بالقواعد السؤال الأول، فلم تُرسل المتابعة؛ هذه نتيجة السؤال الأول."
    return r

entries=[]
for g in gold:
    e={"id":g['id'],"case":g['case'],"group":"primary" if g['group']=='primary' else "supplement","turn":g['turn'],
       "question":g['question'],"followup":g.get('followup',''),
       "gold":{k:g[k] for k in('decision','best','acceptable','partial','forbidden','referral','why')},
       "systems":{k:rec(k,OUT[k][g['id']]) for k,_,_ in SYS}}
    entries.append(e)
E={e['id']:e for e in entries}
def case_pass(sysk,h): return all(E[t]['systems'][sysk]['pass'] for t in TURNS.get(h,[h]))
summary={"version":"v1.0-frozen","commit":"0df7b68f2bed03f7c4c65081c37bb9ecf9641e11","library":"v25 (34 مقطعاً)",
 "case_level":{k:f"{sum(case_pass(k,h) for h in PRIMARY)}/15" for k,_,_ in SYS},
 "turn_level":{k:f"{sum(E[t]['systems'][k]['pass'] for t in E if E[t]['group']=='primary')}/17" for k,_,_ in SYS},
 "supplement":{k:f"{sum(E[h]['systems'][k]['pass'] for h in SUPP)}/3" for k,_,_ in SYS}}
daleel_failed=[h for h in PRIMARY if not case_pass('daleel',h)]
pkg={"package":"Daleel v1.0 — Held-out expert review","summary":summary,"daleel_failed_cases":daleel_failed,"cases":entries}
json.dump(pkg,open('review/daleel-v1.0-review-cases.json','w',encoding='utf-8'),ensure_ascii=False,indent=1)

with open('review/daleel-v1.0-review-cases.csv','w',encoding='utf-8-sig',newline='') as f:
    w=csv.writer(f)
    w.writerow(['ID','الحالة','المجموعة','الـ turn','السؤال','المتابعة','القرار المتوقع','Best','Acceptable','Partial','Forbidden','Referral','سبب الحكم','النظام','القرار القانوني','المقاطع المعروضة','مقطع ممنوع ظهر','نجح','القرار صحيح','الاختيار صحيح','عرض غير مناسب','أجاب حيث يجب الامتناع','جواب حر حيث يجب الامتناع','تصنيف الخطأ','رمز السبب («دليل»)','البوابة («دليل»)','ما ظهر فعلاً'])
    for e in entries:
        g=e['gold']
        for k,name,_ in SYS:
            r=e['systems'][k]
            w.writerow([e['id'],e['case'],e['group'],e['turn'],e['question'],e['followup'],g['decision'],'، '.join(g['best']),'، '.join(g['acceptable']),'، '.join(g['partial']),'، '.join(g['forbidden']),g['referral'],g['why'],
                        name,r['canonical_decision'],'، '.join(r['segments_shown']),'، '.join(r['forbidden_shown']),r['pass'],r['decision_ok'],r['selection_ok'],r['inappropriate'],r['answered_when_should_abstain'],r['free_answer_when_should_abstain'],r['error_category'] or '',r.get('reason_code') or '',r.get('gate') or '',r['what_appeared']])

# ---------- Markdown ----------
L=[]; A=L.append
yn=lambda b:'✓' if b else '✗'
lst=lambda x:'، '.join(x) if x else '—'
A("# «دليل» v1.0 — حزمة المراجعة الخارجية لنتائج القياس المستقل (Held-out)\n")
A("**النسخة المقاسة:** `v1.0-frozen` · commit `0df7b68f2bed03f7c4c65081c37bb9ecf9641e11` · المكتبة v25 (34 مقطعاً معتمداً، نصوص حرفية من مصادرها).  ")
A("**التشغيل:** مرة واحدة لكل نظام، 6 أكتوبر 2026، على مجموعة صُنّفت وأُغلقت قبل التشغيل. لم يُعدَّل أي نظام أو تصنيف بعده.\n")
A("## ما نطلبه من المراجع\n")
A("هذه الحزمة تعرض الحالات والأحكام المرجعية ومخرجات الأنظمة كما هي، دون أي تشخيص أو حل مقترح من فريق المشروع. نطلب منك:\n")
A("1. تشخيص سبب الفشل في كل حالة فاشلة، من واقع ما ظهر للمستخدم وقواعد المنهجية (القسم 3).")
A("2. اقتراح قواعد عامة إن رأيت ذلك، لا استثناءات لأسئلة بعينها.")
A("3. إن رأيت أن حكماً مرجعياً (Gold) نفسه محل نظر، فاذكر ذلك منفصلاً. الحكم المرجعي مغلق، ولا تغيّر ملاحظتك النتيجة الرسمية، لكنها تُسجَّل.\n")
A("## 1. «دليل» باختصار\n")
A("«دليل» يختار لسؤال المبتدئ عن القرآن نصاً معتمداً من مكتبة مراجَعة ويعرضه حرفياً مع مصدره، أو يستوضح، أو يمتنع، أو يحيل. لا يكتب نصاً شرعياً. مساره:\n")
A("1. **فحص بالقواعد** قبل النموذج: الفتوى، وطلب الحديث، وتفسير آية، والقراءات، والسؤال خارج القرآن، والآية المذكورة بنصها أو موضعها، وبعض أسئلة الاستيضاح الثابتة.")
A("2. **الموجّه** (نموذج لغوي يرى أوصاف المقاطع فقط): يقترح مقطعاً أو استيضاحاً أو امتناعاً بسبب، ويسجّل وظيفة السؤال ومسألته وحساسيته.")
A("3. **البوابات:** المقطع المعتمد فقط، والمطابقة السلبية («أسئلة قريبة لا يجيب عنها»)، والحاجة نفسها.")
A("4. **فحص نص المقطع:** يجيب / متعلق جزئياً / لا يجيب، واختيار الجمل التي تجيب.")
A("5. **العرض:** الجمل المختارة حرفياً، والنص كاملاً خلف «أريد التفصيل». الجزئي يُعرض بعنوان «مقطع متعلق بسؤالك».\n")
A("**البدائل الثلاثة** (المكتبة نفسها والأسئلة نفسها والمقيّم نفسه):\n")
A("- **البحث بالكلمات (BM25):** الفحص بالقواعد نفسه، ثم أعلى مقطع بالكلمات فوق عتبة ثابتة، ثم بوابتا «المعتمد فقط» والمطابقة السلبية. لا ينتج في القياس PARTIAL ولا REFER.")
A("- **نموذج عام يرى المكتبة:** النموذج نفسه يرى نصوص المقاطع كاملة ويجيب بحرية مستشهداً بأرقامها. كل استشهاد يُعدّ RECOMMEND، والامتناع بلا سبب يُعدّ NOT_COVERED، فلا ينتج PARTIAL ولا REFER.")
A("- **النموذج العام بعد الفحص بالقواعد:** ما يلتقطه الفحص بالقواعد يعامل كما في «دليل»، وما سواه للنموذج العام. قيد معروف: إن التقط الفحص السؤال الأول، لا تُرسل المتابعة (حدث في H12).\n")
A("## 2. النتائج الرسمية\n")
A("| المقياس | «دليل» | BM25 | النموذج العام | النموذج العام + الفحص |\n|---|---|---|---|---|")
A(f"| النجاح على مستوى الحالة (15) | **{summary['case_level']['daleel']}** | {summary['case_level']['bm25']} | {summary['case_level']['general']} | {summary['case_level']['general_pre']} |")
A(f"| النجاح على مستوى الـ turn (17، تشخيصي) | {summary['turn_level']['daleel']} | {summary['turn_level']['bm25']} | {summary['turn_level']['general']} | {summary['turn_level']['general_pre']} |")
inapp={k:sum(any(E[t]['systems'][k]['inappropriate'] for t in TURNS.get(h,[h])) for h in PRIMARY) for k,_,_ in SYS}
A(f"| حالات عُرض فيها مقطع غير مناسب (15) | **{inapp['daleel']}/15** | {inapp['bm25']}/15 | {inapp['general']}/15 | {inapp['general_pre']}/15 |")
ABST=[t for t in E if E[t]['group']=='primary' and E[t]['gold']['decision'] in('NOT_COVERED','REFER')]
uns={k:sum(E[t]['systems'][k]['answered_when_should_abstain'] for t in ABST) for k,_,_ in SYS}
fre={k:sum(E[t]['systems'][k]['free_answer_when_should_abstain'] for t in ABST) for k,_,_ in SYS}
A(f"| أجاب حيث يجب الامتناع (10 turns، المقيّم) | {uns['daleel']}/10 | {uns['bm25']}/10 | {uns['general']}/10 | {uns['general_pre']}/10 |")
A(f"| جواب حر بلا مقطع حيث يجب الامتناع (تدقيق إضافي) | {fre['daleel']}/10 | {fre['bm25']}/10 | {fre['general']}/10 | {fre['general_pre']}/10 |")
A(f"| الملحق HX01–HX03 | {summary['supplement']['daleel']} | {summary['supplement']['bm25']} | {summary['supplement']['general']} | {summary['supplement']['general_pre']} |\n")
A("**قيود:** العينة صغيرة؛ على مستوى الحالة الفرق بين «دليل» وكل بديل غير دالّ إحصائياً (McNemar الدقيق p = 0.063، 0.125، 0.063). مستوى الـ turn تشخيصي. PARTIAL فشل في الأنظمة الأربعة (0/5). بعض البدائل لا تنتج بعض القرارات بنيوياً.\n")
A("## 3. قواعد المنهجية الحالية للقرارات\n")
A("| القرار | القاعدة | ما يراه المستخدم |\n|---|---|---|")
A("| **RECOMMEND** | المقطع يجيب المسألة المطلوبة نفسها مباشرة ضمن حدوده. | النص المعتمد (الجمل المختارة) مع مصدره، ثم «هل أجاب هذا عن سؤالك؟» |")
A("| **PARTIAL** | المقطع يجيب جزءاً معتبراً من الحاجة، لكن عنصراً صريحاً من السؤال يقع خارج ما يثبته أو يغطيه. لا يكفي أن يكون المقطع غير شامل لكل تفاصيل الموضوع، ولا يكفي وجود معلومات مرتبطة. | النص بعنوان «مقطع متعلق بسؤالك» وسطر يعلن أنه لا يجيب عن السؤال كاملاً. |")
A("| **NOT_COVERED** | لا يوجد في المكتبة مقطع يؤدي المهمة المطلوبة أصلاً. يُفضَّل الامتناع على عرض نص قريب الموضوع لا يجيب. | رسالة امتناع صادقة (وتحيل إلى مصدر تفسير إن كان طلب تفسير). |")
A("| **REFER** | الفتوى، والحكم في حالة شخصية، وطلب المستخدم مختصاً — فقط. | رسالة إحالة إلى أهل العلم أو جهة إفتاء. |")
A("| **CLARIFY** | سؤال واحد حين يحتمل السؤال معنى يجيب عنه مقطع ومعنى لا يجيب عنه، أو يغيّر المقصد المادة المناسبة. | سؤال استيضاح بخيارات محددة. |\n")
A("**المطابقة السلبية:** لكل مقطع «أسئلة قريبة لا يجيب عنها» كتبها المراجع؛ هي لما لا يصلح للسؤال أصلاً، وتمنع عرض المقطع.  ")
A("**تطبيع القرار في المقيّم:** كل امتناع غير الفتوى وطلب المختص (تفسير، خارج الموضوع، آية غير موجودة، غير مغطى) يُعدّ NOT_COVERED؛ الفتوى وطلب المختص REFER؛ عرض آية وحدها يُعدّ VERSE، ويُحسب «أجاب حيث يجب الامتناع» إن كان المتوقع امتناعاً.\n")
A("**قواعد النجاح:**\n")
A("- RECOMMEND: القرار RECOMMEND، وأول مقطع من Best أو Acceptable.")
A("- PARTIAL: القرار PARTIAL، وأول مقطع من Best أو Acceptable أو Partial.")
A("- NOT_COVERED: امتناع بلا أي مقتطف. REFER: امتناع بإحالة بلا أي مقتطف.")
A("- ظهور مقطع من Forbidden = عرض غير مناسب. حالة المتابعة تنجح فقط إذا نجح الـ turnان.\n")
A("**تصنيف الخطأ (آلي من المقيّم):** DECISION_ERROR = القرار القانوني مخالف للمتوقع؛ SELECTION_ERROR = القرار صحيح والمقطع الأول ليس من المسموح؛ FOLLOWUP_ERROR = فشل في turn المتابعة؛ OTHER = غير ذلك.\n")
A("**رموز السبب والبوابة في مخرجات «دليل» (وصف لما سجّله النظام، لا تشخيص):**\n")
for k,v in REASON_DESC.items(): A(f"- `{k}`: {v}")
for k,v in GATE_DESC.items(): A(f"- بوابة `{k}`: {v}")
A("")
def case_block(h):
    ids=TURNS.get(h,[h])
    g0=E[ids[0]]
    A(f"### {h}\n")
    for t in ids:
        e=E[t]; g=e['gold']
        q=e['question'] if not e['followup'] else f"{e['question']} ← المتابعة: {e['followup']}"
        label='' if len(ids)==1 else (' — الـ turn الأول' if t.endswith('T1') else ' — المتابعة (بعد السؤال الأول)')
        A(f"**{t}{label}**  ")
        A(f"**السؤال:** {q}  ")
        A(f"**الحكم المرجعي:** {g['decision']} · Best: {lst(g['best'])} · Acceptable: {lst(g['acceptable'])} · Partial: {lst(g['partial'])} · Forbidden: {lst(g['forbidden'])}"+(f" · Referral: {g['referral']}" if g['referral'] else '')+"  ")
        A(f"**سبب الحكم:** {g['why']}\n")
        A("| النظام | القرار | المقاطع المعروضة | ممنوع ظهر | نجح | تصنيف الخطأ |\n|---|---|---|---|---|---|")
        for k,name,_ in SYS:
            r=e['systems'][k]
            A(f"| {name} | {r['canonical_decision']} | {lst(r['segments_shown'])} | {lst(r['forbidden_shown'])} | {yn(r['pass'])} | {r['error_category'] or '—'} |")
        A("")
        d=e['systems']['daleel']
        A(f"- **ما ظهر في «دليل»:** {d['what_appeared']}")
        A(f"- **ما سجّله «دليل»:** القرار {d['canonical_decision']}؛ رمز السبب `{d.get('reason_code') or '—'}`؛ البوابة `{d.get('gate') or '—'}`"+(f"؛ وظيفة السؤال «{d['router_task']}»؛ المسألة كما صاغها الموجّه: «{d['router_issue']}»" if d.get('router_task') else "؛ (لم يصل السؤال إلى الموجّه: التقطه الفحص بالقواعد)"))
        for k,name,_ in SYS[1:]:
            r=e['systems'][k]
            A(f"- **ما ظهر في {name}:** {r['what_appeared']}"+(f" — **{r['note']}**" if r.get('note') else ''))
        A("")
A("## 4. حالات «دليل» الفاشلة الثماني (مستوى الحالة)\n")
A(f"{lst(daleel_failed)}. التفصيل الكامل لكل منها في القسم 5. ملخص ما سجّله المقيّم دون تفسير:\n")
A("| الحالة | المتوقع | قرار «دليل» | المقاطع المعروضة | تصنيف الخطأ | رمز السبب | البوابة |\n|---|---|---|---|---|---|---|")
for h in daleel_failed:
    for t in TURNS.get(h,[h]):
        d=E[t]['systems']['daleel']
        if d['pass']: continue
        A(f"| {t} | {E[t]['gold']['decision']} | {d['canonical_decision']} | {lst(d['segments_shown'])} | {d['error_category']} | `{d.get('reason_code') or '—'}` | `{d.get('gate') or '—'}` |")
A("")
A("## 5. الحالات الأساسية H01–H15: الحكم المرجعي ومخرجات الأنظمة\n")
for h in PRIMARY: case_block(h)
A("## 6. الملحق HX01–HX03 (منفصل، لا يدخل في النسبة الأساسية)\n")
for h in SUPP: case_block(h)
used=set()
for e in entries:
    g=e['gold']; used|=set(g['best']+g['acceptable']+g['partial']+g['forbidden'])
    for r in e['systems'].values(): used|=set(r['segments_shown'])
A("## الملحق أ: ملاحظات على المخرجات المحفوظة\n")
A("- نص الآية المعروضة في حالات VERSE لم يُحفظ في مخرجات القياس.")
A("- النموذج العام: حُفظ أول 600 حرف من ردّه **الأول** فقط؛ نص ردّ المتابعة لم يُحفظ، وإن حُفظ تصنيفه وأرقام المقاطع التي استشهد بها.")
A("- النموذج العام بعد الفحص: لم يُحفظ نص ردّه؛ حُفظ تصنيفه وأرقام المقاطع.")
A("- BM25 و«دليل» لا يكتبان نصاً: ما يظهر هو نص المقطع المعتمد أو قالب ثابت.")
A("- حدثت محاولة تقنية أولى غير مكتملة لتشغيل «دليل»؛ عالج الخادم H01 ثم توقف المقيّم بسبب غياب حقل بنيوي `type` في ملف تحويل Held-out. لم تُنتج نتيجة تقييم، ولم تُعرض مخرجات الحالة أو تُستخدم في أي تعديل. أُصلح Schema فقط، دون تغيير المحرك أو المكتبة أو Gold، ثم أُجري أول تشغيل مكتمل.\n")
A("## الملحق ب: نصوص المقاطع المذكورة في الحالات (كما يعرضها «دليل»)\n")
A("النصوص حرفية من المكتبة المجمّدة. الآيات بين ﴿﴾ برسم مصحف مجمع الملك فهد كما تُعرض. «[…]» موضع قصّ من المصدر.\n")
def k_(i): return int(i.split('-')[1])
for i in sorted(used,key=k_):
    s=segs[i]
    A(f"### {i}\n")
    A(f"**المصدر:** {s['src_title']} — {s['location']}  ")
    A(f"**يجيب عن (ANSWERS):** {s['about']}  ")
    A(f"**حدود الدليل:** {s['method'].get('EVIDENCE_LIMITS','')}  ")
    A(f"**لا يجيب عن:** {s['method'].get('DOES_NOT_ANSWER','')}  ")
    A(f"**أسئلة قريبة لا يجيب عنها:** {lst(s['not_for'])}\n")
    A("> "+s['text'].replace('\n','\n> ')+"\n")
open('review/daleel-v1.0-expert-review.md','w',encoding='utf-8').write('\n'.join(L))
print('passages in appendix',len(used)); print(summary); print('failed',daleel_failed)
