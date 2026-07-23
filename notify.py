"""Compara o JSON recém-gerado com o anterior e, se houver instâncias novas,
notifica via Pushover apenas a QUANTIDADE de instâncias novas.

- Primeira execução (sem JSON anterior): tudo conta como novo.
- Sem instâncias novas: não envia nada (silencioso).

Lê PUSHOVER_TOKEN e PUSHOVER_USER do ambiente. Usa só a biblioteca padrão.
"""

import argparse
import json
import os
import urllib.error
import urllib.parse
import urllib.request

PUSHOVER_URL = "https://api.pushover.net/1/messages.json"


def load_instance_types(path: str) -> set[str]:
    """Lê os instance_type de um JSON gerado pelo main.py (vazio se não existir)."""
    if not os.path.exists(path):
        return set()
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return {inst["instance_type"] for inst in data.get("instances", [])}


def send_pushover(title: str, message: str) -> None:
    token = os.environ["PUSHOVER_TOKEN"]
    user = os.environ["PUSHOVER_USER"]
    payload = urllib.parse.urlencode(
        {"token": token, "user": user, "title": title, "message": message}
    ).encode()
    request = urllib.request.Request(PUSHOVER_URL, data=payload)
    try:
        with urllib.request.urlopen(request) as response:
            response.read()
    except urllib.error.HTTPError as error:
        body = error.read().decode(errors="replace")
        # O corpo do Pushover indica qual campo está inválido (sem expor o valor).
        print(f"Pushover recusou (HTTP {error.code}): {body}")
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--new", default="instances_sa-east-1.json")
    parser.add_argument("--old", default="previous.json")
    args = parser.parse_args()

    new_types = load_instance_types(args.new)
    old_types = load_instance_types(args.old)

    added = sorted(new_types - old_types)
    print(f"Instâncias novas: {len(added)}")

    if not added:
        print("Nada novo — nenhuma notificação enviada.")
        return

    send_pushover(
        title="EMR sa-east-1",
        message=f"{len(added)} nova(s) instância(s) EMR disponível(is) em São Paulo.",
    )
    print("Notificação enviada via Pushover.")


if __name__ == "__main__":
    main()
