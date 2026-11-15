import httpx,json,re,sys,io
from PIL import Image
h={'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36'}
d=json.load(open('search.json',encoding='utf-8'))
for q,v in d.items():
  for name,url,price in v:
    if re.search(r'\d+x\d',name) or 'LUX' in name or 'Ελιές' in name: continue
    pid=url.split('Products/')[1].replace('/','_')
    # try original-size variant
    big=re.sub(r'/images/Product/(\d+/)?files/','/files/',url)
    for u in (big,url):
      try:
        r=httpx.get(u,headers=h,timeout=30)
        if r.status_code==200 and r.headers.get('content-type','').startswith('image'):
          im=Image.open(io.BytesIO(r.content)); im.load()
          fn=f'raw/{pid.rsplit(".",1)[0]}.png'; im.convert('RGBA').save(fn)
          print(im.size,'big' if u==big else 'small',name,fn); break
      except Exception as e: print('ERR',u,e)
