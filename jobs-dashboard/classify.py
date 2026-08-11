# -*- coding: utf-8 -*-
"""Classificação bilíngue de área e senioridade para o painel público."""
import re
import unicodedata


def _norm(value):
    text = unicodedata.normalize("NFKD", str(value or ""))
    return text.encode("ascii", "ignore").decode().lower()


SENIORITY_PATTERNS = [
    ("Estágio", r"estagi|intern(ship)?|\bstage\b"),
    ("Trainee/Aprendiz", r"trainee|aprendiz"),
    ("Júnior/Assistente", r"junior|\bjr\b|entry[- ]?level|assistente|auxiliar"),
    ("Pleno", r"pleno|\bpl\b|mid[- ]?level|\bmid\b|\bii\b"),
    ("Sênior/Especialista", r"senior|\bsr\b|especialista|specialist|staff|principal|\biii\b"),
    ("Liderança", r"coordenador|supervisor|gerente|manager|\blead\b|head|diretor|director|\bvp\b|chefe"),
]

STRUCTURED_LEVEL = {
    "internship": "Estágio",
    "entry level": "Júnior/Assistente",
    "mid level": "Pleno",
    "senior level": "Sênior/Especialista",
    "management": "Liderança",
    "estagio": "Estágio",
    "trainee": "Trainee/Aprendiz",
    "aprendiz": "Trainee/Aprendiz",
    "junior/assistente": "Júnior/Assistente",
    "junior": "Júnior/Assistente",
    "entry": "Júnior/Assistente",
    "assistent": "Júnior/Assistente",
    "pleno": "Pleno",
    "mid": "Pleno",
    "senior/especialista": "Sênior/Especialista",
    "senior": "Sênior/Especialista",
    "lideranca": "Liderança",
    "coordinator": "Liderança",
    "manager": "Liderança",
    "director": "Liderança",
    "executive": "Liderança",
    "supervisao/coordenacao": "Liderança",
    "gerencial e executivos": "Liderança",
}

AREA_KEYWORDS = {
    "Dados, BI e IA": [
        r"analista de dados", r"cientista de dados", r"data analyst", r"data scientist",
        r"data engineer", r"engenheiro de dados", r"business intelligence", r"power bi",
        r"analytics", r"machine learning", r"inteligencia artificial", r"\bia\b", r"\bai\b",
        r"\betl\b", r"\bsql\b", r"\bdados\b", r"\bdata\b", r"big data", r"llm",
    ],
    "Suporte, Atendimento e CS": [
        r"customer success", r"customer support", r"customer experience", r"technical support",
        r"suporte", r"atendimento", r"service desk", r"help ?desk", r"implantacao",
        r"implementation", r"sustentacao", r"application support", r"production support",
    ],
    "TI e Desenvolvimento": [
        r"desenvolvedor", r"developer", r"software engineer", r"engenheiro de software",
        r"backend", r"front-?end", r"full ?stack", r"programador", r"devops", r"\bsre\b",
        r"\bqa\b", r"quality assurance", r"mobile", r"android", r"\bios\b", r"\bjava\b",
        r"python", r"react", r"node", r"\.net", r"cloud", r"infraestrutura", r"cyber",
        r"seguranca da informacao", r"salesforce", r"sap", r"rpa",
    ],
    "Produto e Projetos": [
        r"product manager", r"gerente de produto", r"product owner", r"\bproduto\b",
        r"project manager", r"gerente de projetos", r"\bpmo\b", r"scrum", r"agile",
        r"business analyst", r"analista de negocios",
    ],
    "Design": [r"designer", r"\bux\b", r"\bui\b", r"ux/ui", r"user experience", r"design"],
    "Marketing e Comunicação": [
        r"marketing", r"growth", r"\bseo\b", r"midia", r"conteudo", r"content",
        r"social media", r"brand", r"comunicacao", r"publicidade", r"copywriter", r"\bcrm\b",
    ],
    "Comercial e Vendas": [
        r"vendas", r"\bsales\b", r"comercial", r"\bsdr\b", r"\bbdr\b",
        r"account executive", r"business development", r"pre-vendas", r"representante", r"closer",
    ],
    "Financeiro e Contábil": [
        r"financeiro", r"finance", r"contabil", r"controladoria", r"accounting", r"fp&a",
        r"tesouraria", r"fiscal", r"auditor", r"cobranca", r"credito", r"billing",
    ],
    "Operações e Logística": [
        r"operacoes", r"operations", r"logistica", r"supply", r"\bops\b", r"processos",
        r"\bpcp\b", r"producao", r"administrativ", r"back ?office", r"compras", r"procurement",
    ],
    "RH e Pessoas": [
        r"recursos humanos", r"\brh\b", r"people", r"talent", r"recrut", r"human resources",
        r"departamento pessoal", r"remuneracao", r"beneficios",
    ],
    "Jurídico e Compliance": [r"juridic", r"\blegal\b", r"advogad", r"compliance", r"lgpd", r"contratos"],
    "Engenharia e Indústria": [
        r"engenheiro", r"engenheira", r"engenharia", r"manutencao", r"industrial", r"civil",
        r"eletric", r"mecanic", r"obra", r"tecnico de campo",
    ],
    "Saúde": [r"medic", r"enferm", r"psicolog", r"nutric", r"farmac", r"saude", r"clinica", r"terapeut"],
    "Educação": [r"professor", r"educacao", r"pedagog", r"instrutor", r"tutor", r"ensino", r"escola", r"academico"],
}

CATEGORY_MAP = {
    "data": "Dados, BI e IA", "data science": "Dados, BI e IA", "analytics": "Dados, BI e IA",
    "dados, bi e ia": "Dados, BI e IA",
    "software development": "TI e Desenvolvimento", "development": "TI e Desenvolvimento",
    "engineering": "TI e Desenvolvimento", "devops and sysadmin": "TI e Desenvolvimento",
    "system administration": "TI e Desenvolvimento", "qa": "TI e Desenvolvimento",
    "ti e desenvolvimento": "TI e Desenvolvimento",
    "product": "Produto e Projetos", "produto e projetos": "Produto e Projetos",
    "design": "Design", "marketing": "Marketing e Comunicação",
    "marketing e comunicacao": "Marketing e Comunicação",
    "sales": "Comercial e Vendas", "sales and marketing": "Comercial e Vendas",
    "vendas e comercial": "Comercial e Vendas", "comercial e vendas": "Comercial e Vendas",
    "finance": "Financeiro e Contábil", "finance and legal": "Financeiro e Contábil",
    "financeiro e contabil": "Financeiro e Contábil",
    "human resources": "RH e Pessoas", "hr": "RH e Pessoas", "rh e recrutamento": "RH e Pessoas",
    "customer service": "Suporte, Atendimento e CS", "customer support": "Suporte, Atendimento e CS",
    "suporte, atendimento e cs": "Suporte, Atendimento e CS",
    "operations": "Operações e Logística", "operacoes e administrativo": "Operações e Logística",
    "juridico e compliance": "Jurídico e Compliance", "engenharia e industria": "Engenharia e Indústria",
    "saude": "Saúde", "educacao": "Educação",
}

AREA_REGEX = {area: [re.compile(pattern, re.I) for pattern in patterns]
              for area, patterns in AREA_KEYWORDS.items()}


def seniority(item):
    for value in item.get("levels") or []:
        mapped = STRUCTURED_LEVEL.get(_norm(value).strip())
        if mapped:
            return mapped
    title = f" { _norm(item.get('title')) } "
    for name, pattern in reversed(SENIORITY_PATTERNS):
        if re.search(pattern, title, re.I):
            return name
    return "Não informado"


def area(item):
    for value in item.get("categories") or []:
        mapped = CATEGORY_MAP.get(_norm(value).strip())
        if mapped:
            return mapped
    title = f" {_norm(item.get('title'))} "
    description = _norm(item.get("description"))[:600]
    best, score_best = "Outros", 0
    for name, patterns in AREA_REGEX.items():
        score = sum(3 for pattern in patterns if pattern.search(title))
        score += sum(1 for pattern in patterns if pattern.search(description))
        if score > score_best:
            best, score_best = name, score
    return best if score_best >= 3 else "Outros"


def classify(item):
    item["area"] = area(item)
    item["seniority"] = seniority(item)
    return item
