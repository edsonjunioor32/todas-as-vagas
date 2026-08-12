# -*- coding: utf-8 -*-
"""TOTVS public careers listing."""
from html.parser import HTMLParser
from ._common import job, work_model_label
from ._http import get_text
URL="https://atracaodetalentos.totvs.app/vempratotvs/extended"
class P(HTMLParser):
 def __init__(self): super().__init__(convert_charrefs=True);self.a=None;self.rows=[]
 def handle_starttag(self,t,attrs):
  if t=="a" and self.a is None:
   href=dict(attrs).get("href","")
   if href and "totvs" in href.lower():self.a=[href,[]]
 def handle_endtag(self,t):
  if t=="a" and self.a:
   if self.a[1]:self.rows.append(self.a)
   self.a=None
 def handle_data(self,d):
  if self.a and d.strip():self.a[1].append(d.strip())
def fetch():
 p=P();p.feed(get_text(URL,timeout=45,retries=2));out={}
 for href,parts in p.rows:
  title=parts[0]
  if title in {"Vagas disponíveis","TOTVS"}:continue
  key=href or title
  out[key]=job("totvs",key,title,"TOTVS",href,work_model=work_model_label(raw=" ".join(parts)),city=parts[1] if len(parts)>1 else "",country="BR",market="BR")
 return list(out.values())
