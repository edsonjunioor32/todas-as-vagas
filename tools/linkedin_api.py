#!/usr/bin/env python3
"""
Cliente nativo da LinkedIn REST API (Community Management API).
Permite publicação direta de posts com imagem em páginas de empresas (Organizações)
sem dependência de webhooks intermediários (como Make.com).
"""
from __future__ import annotations

import json
import mimetypes
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

LINKEDIN_REST_BASE = "https://api.linkedin.com/rest"
DEFAULT_ORG_URN = "urn:li:organization:146671035"
API_VERSION = "202611"
PROTOCOL_VERSION = "2.0.0"


class LinkedInAPIError(Exception):
    """Erro retornado pela LinkedIn REST API."""
    def __init__(self, message: str, status_code: int | None = None, response_body: str | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.response_body = response_body


def _make_headers(token: str, content_type: str | None = "application/json") -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {token.strip()}",
        "X-Restli-Protocol-Version": PROTOCOL_VERSION,
        "Linkedin-Version": API_VERSION,
        "User-Agent": "TodasAsVagasBot/1.0 (+https://github.com/edsonjunioor32/todas-as-vagas)",
    }
    if content_type:
        headers["Content-Type"] = content_type
    return headers


def initialize_image_upload(token: str, org_urn: str = DEFAULT_ORG_URN) -> tuple[str, str]:
    """
    Inicializa o registro de upload de uma imagem para a página da organização.
    Retorna uma tupla (image_urn, upload_url).
    """
    url = f"{LINKEDIN_REST_BASE}/images?action=initializeUpload"
    payload = {
        "initializeUploadRequest": {
            "owner": org_urn
        }
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=_make_headers(token))

    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            res_json = json.loads(resp.read().decode("utf-8"))
            val = res_json.get("value", {})
            image_urn = val.get("image")
            upload_url = val.get("uploadUrl")
            if not image_urn or not upload_url:
                raise LinkedInAPIError(f"Resposta inválida de initializeUpload: {res_json}")
            return image_urn, upload_url
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise LinkedInAPIError(f"HTTP {exc.code} ao inicializar upload: {body}", status_code=exc.code, response_body=body) from exc


def upload_image_binary(upload_url: str, image_bytes: bytes, token: str, content_type: str = "image/jpeg") -> None:
    """
    Faz o upload binário (PUT) da imagem para o endpoint temporário da LinkedIn CDN.
    """
    headers = {
        "Authorization": f"Bearer {token.strip()}",
        "Content-Type": content_type,
    }
    req = urllib.request.Request(upload_url, data=image_bytes, headers=headers, method="PUT")

    try:
        with urllib.request.urlopen(req, timeout=40) as resp:
            if resp.status not in (200, 201):
                raise LinkedInAPIError(f"Status inesperado no upload binário: HTTP {resp.status}")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise LinkedInAPIError(f"HTTP {exc.code} no upload binário: {body}", status_code=exc.code, response_body=body) from exc


def load_image_bytes(image_path_or_url: str) -> tuple[bytes, str]:
    """
    Carrega os bytes da imagem a partir de um arquivo local ou URL.
    Retorna (bytes, content_type).
    """
    local_p = Path(image_path_or_url)
    if local_p.exists() and local_p.is_file():
        mime, _ = mimetypes.guess_type(local_p.name)
        return local_p.read_bytes(), mime or "image/jpeg"

    # Se for uma URL
    req = urllib.request.Request(image_path_or_url, headers={"User-Agent": "TodasAsVagasBot/1.0"})
    with urllib.request.urlopen(req, timeout=25) as resp:
        content_type = resp.headers.get("Content-Type", "image/jpeg").split(";")[0].strip()
        return resp.read(), content_type


def upload_image(image_path_or_url: str, token: str, org_urn: str = DEFAULT_ORG_URN) -> str:
    """
    Fluxo completo de upload de imagem para o LinkedIn:
    1. Lê imagem local/remota
    2. Inicializa upload no endpoint /rest/images
    3. Envia o binário
    Retorna o image_urn (ex: 'urn:li:image:C4D...').
    """
    image_bytes, content_type = load_image_bytes(image_path_or_url)
    image_urn, upload_url = initialize_image_upload(token, org_urn)
    upload_image_binary(upload_url, image_bytes, token, content_type)
    return image_urn


def create_post(
    commentary: str,
    image_urn: str | None = None,
    token: str = "",
    org_urn: str = DEFAULT_ORG_URN,
    media_title: str = "Todas as Vagas"
) -> str:
    """
    Cria uma publicação no feed da página da organização via POST /rest/posts.
    Retorna o URN do post criado (extraído do cabeçalho x-restli-id).
    """
    url = f"{LINKEDIN_REST_BASE}/posts"
    payload: dict[str, Any] = {
        "author": org_urn,
        "commentary": commentary,
        "visibility": "PUBLIC",
        "distribution": {
            "feedDistribution": "MAIN_FEED",
            "targetEntities": [],
            "thirdPartyDistributionChannels": []
        },
        "lifecycleState": "PUBLISHED",
        "isReshareDisabledByAuthor": False
    }

    if image_urn:
        payload["content"] = {
            "media": {
                "id": image_urn,
                "title": media_title
            }
        }

    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=_make_headers(token))

    try:
        with urllib.request.urlopen(req, timeout=25) as resp:
            post_urn = resp.headers.get("x-restli-id", "")
            return post_urn or "urn:li:share:created"
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise LinkedInAPIError(f"HTTP {exc.code} ao criar post: {body}", status_code=exc.code, response_body=body) from exc


def publish_to_linkedin(
    commentary: str,
    image_path_or_url: str | None,
    token: str,
    org_urn: str = DEFAULT_ORG_URN
) -> str:
    """
    Coordena a publicação completa (upload de imagem opcional + postagem de feed).
    """
    image_urn = None
    if image_path_or_url:
        print("Fazendo upload da imagem diretamente para a LinkedIn Images API...")
        image_urn = upload_image(image_path_or_url, token, org_urn)
        print(f"Imagem enviada com sucesso! URN: {image_urn}")

    print("Publicando post no feed oficial da página...")
    post_urn = create_post(commentary=commentary, image_urn=image_urn, token=token, org_urn=org_urn)
    print(f"Post publicado com sucesso! URN: {post_urn}")
    return post_urn
