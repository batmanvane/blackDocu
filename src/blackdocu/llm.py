"""Ollama-Zugriff: wählt Studio oder Desktop, mit Fallback.

Nur lokale/Tailscale-Hosts. Externe Modelle sind in Phase 1 ausgeschlossen.
"""

from __future__ import annotations

import json
import re
import urllib.request
from typing import Any

import ollama


def assert_local(url: str) -> str:
    """Erlaubt nur Loopback, private Netze und Tailscale (100.64.0.0/10) – Review 1.17.

    Verhindert, dass eine geänderte config.yaml Texte an einen Dienst im Internet schickt.
    """
    import ipaddress
    from urllib.parse import urlparse

    host = urlparse(url).hostname or ""
    if host == "localhost":
        return url
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        raise ValueError(f"Ollama-Host muss eine IP sein (lokal/Tailnet), nicht {host!r}") from None
    if ip.is_loopback or ip.is_private or ip in ipaddress.ip_network("100.64.0.0/10"):
        return url
    raise ValueError(f"Ollama-Host {host} liegt nicht im lokalen Netz/Tailnet – abgelehnt.")


def host_reachable(url: str, timeout: float = 3.0) -> bool:
    try:
        with urllib.request.urlopen(f"{url}/api/version", timeout=timeout) as r:
            return r.status == 200
    except OSError:
        return False


def pick_host(cfg: dict[str, Any]) -> tuple[str, str]:
    """Gibt (name, url) des ersten erreichbaren Hosts zurück."""
    llm = cfg["llm"]
    for name in (llm["host"], llm.get("fallback")):
        if name and host_reachable(llm["hosts"][name]):
            return name, llm["hosts"][name]
    raise RuntimeError("Kein Ollama-Host erreichbar (studio/desktop).")


def _extract_json(content: str) -> Any:
    """JSON aus der Antwort holen, auch wenn das Modell Text oder ```json drumherum schreibt."""
    content = re.sub(r"<think>.*?</think>", "", content, flags=re.S).strip()
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", content, re.S)
        if not m:
            raise
        return json.loads(m.group(0))


def chat_json(cfg: dict[str, Any], system: str, user: str, host: str | None = None) -> Any:
    """Schickt einen Prompt und erwartet JSON als Antwort.

    Manche Modelle (z. B. qwen3.6 in Ollama) lehnen `format="json"` ab (HTTP 501).
    Dann wird ohne Format gefragt und das JSON aus dem Text gelesen.
    """
    url = assert_local(cfg["llm"]["hosts"][host] if host else pick_host(cfg)[1])
    client = ollama.Client(host=url, timeout=cfg["llm"].get("timeout", 600))
    kw = dict(
        model=cfg["llm"]["model"],
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        think=cfg["llm"].get("think", False),
        options={"temperature": cfg["llm"].get("temperature", 0.0),
                 "num_ctx": cfg["llm"].get("num_ctx", 8192)},
    )
    try:
        resp = client.chat(format="json", **kw)
    except ollama.ResponseError as e:
        if e.status_code != 501:
            raise
        resp = client.chat(**kw)
    return _extract_json(resp["message"]["content"])


def available_hosts(cfg: dict[str, Any]) -> list[str]:
    """Alle erreichbaren Hosts, für parallele Läufe (Studio + Desktop)."""
    return [n for n, u in cfg["llm"]["hosts"].items() if host_reachable(u)]
