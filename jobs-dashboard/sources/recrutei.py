# -*- coding: utf-8 -*-
"""Configured public Recrutei career pages."""
import re
from html.parser import HTMLParser
from urllib.parse import urljoin
from ._common import job, work_model_label
from ._http import get_text

PAGES = {
    "full-sales-system": "Full Sales System",
    "singularis-rh": "Singularis RH",
    "singularis-rh/contratacaoacelerada": "Singularis RH",
    "rehva-tech": "Rehva Tech",
    "ataway-do-brasil": "Ataway do Brasil",
    "bm-vagas": "BM Vagas",
    "thera-consulting": "Thera Consulting",
    "fourhands-brasil": "Fourhands Brasil",
    "emiteai-solucoes-em-tecnologia": "Emiteai Soluções em Tecnologia",
    "grupo-regazzo": "Grupo Regazzo",
    "meirelespessoaseeducacao": "Meireles Pessoas e Educação",
    "luzcon-digital-ltda": "Luzcon Digital",
    "alpha-estagio": "Alpha Estágio",
    "3am-it-services-2": "3AM IT Services",
}
HOST = "https://jobs.recrutei.com.br"
CARD = re.compile(r"/([^/]+)/vacancy/(\d+)-", re.I)
CONTRACT = re.compile(r"^(?:CLT|PJ|CLT ou PJ|Estágio|Temporário)$", re.I)
class Cards(HTMLParser):
 def __init__(self):
  super().__init__(convert_charrefs=True); self.card=None; self.rows=[]
 def handle_starttag(self,tag,attrs):
  href=dict(attrs).get("href",""); match=CARD.search(href)
  if tag=="a" and self.card is None and match:self.card={"id":match.group(2),"url":urljoin(HOST,href),"parts":[]}
 def handle_endtag(self,tag):
  if tag=="a" and self.card:
   if self.card["parts"]:self.rows.append(self.card)
   self.card=None
 def handle_data(self,data):
  if self.card and data.strip():self.card["parts"].append(data.strip())
def fetch():
 out={}
 for path, company in PAGES.items():
  parser=Cards(); parser.feed(get_text(f"{HOST}/{path}",timeout=40,retries=2))
  for card in parser.rows:
   parts=card["parts"]; contract=next((x for x in parts[1:] if CONTRACT.match(x)),"")
   location=next((x for x in reversed(parts[1:]) if x!=contract),"")
   key=f"{path}:{card['id']}"
   out[key]=job("recrutei",key,parts[0],company,card["url"],work_model=work_model_label(raw=location),city=location,country="BR",market="BR",contract_types=re.split(r"\s+ou\s+",contract,flags=re.I) if contract else [])
 return list(out.values())
