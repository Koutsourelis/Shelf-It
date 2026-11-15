import httpx,re,json,sys,html
h={'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36'}
qs=sys.argv[1:]
out={}
for q in qs:
    t=httpx.get('https://www.sklavenitis.gr/apotelesmata-anazitisis/',params={'Query':q},headers=h,timeout=30,follow_redirects=True).content.decode('utf-8','replace')
    for m in re.finditer(r'<img src="(https://s1\.sklavenitis\.gr/images/Product/[^"]+)" alt="([^"]*)"',t):
        tail=t[m.end():m.end()+3000]
        p=re.search(r'data-price="([\d,]+)"',tail)
        out.setdefault(q,[]).append((html.unescape(m.group(2)),m.group(1),p.group(1) if p else None))
for q,v in out.items():
    print('==',q)
    for x in v[:14]: print('  ',x[2],'|',x[0],'|',x[1].split('Products/')[1])
json.dump(out,open('search.json','w',encoding='utf-8'),ensure_ascii=False,indent=1)
