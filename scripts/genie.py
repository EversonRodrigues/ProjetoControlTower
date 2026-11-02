#!/usr/bin/env python3
"""Conversa com o Genie Agent do Projeto Farol pela CLI.

  python scripts/genie.py perguntar "Farol · Diretoria" "<pergunta>" --profile <perfil>
  python scripts/genie.py benchmark  "Farol · Diretoria" llm/genie-benchmark.json --profile <perfil>

O espaco e resolvido PELO TITULO, nao pelo id: o id muda a cada
recriacao do recurso do bundle, o titulo nao.

Por que o benchmark julga por regra declarada e nao por um juiz LLM: as
respostas certas sao numeros conhecidos do seed 42, entao uma regra da um
placar auditavel e reproduzivel -- "17/20 hoje" e "17/20 amanha". Um juiz
LLM acrescentaria variancia justamente no instrumento de medida, e o loop
do prompt ("se der menos de 16/20, conserte a INSTRUCAO") perderia o
sinal: nao daria para saber se o Genie piorou ou se o juiz mudou de ideia.

O palheiro em que a verificacao procura e o texto da resposta MAIS as
linhas do resultado achatadas. Assim um numero que o Genie arredondou na
prosa ("R$ 6,5 mi") ainda e encontrado no valor cru da linha, e a nota
mede o SQL que ele escreveu -- que e o que a instrucao controla -- e nao
a redacao dele.
"""
import argparse
import json
import re
import sys
import time
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_sql import cli  # mesmo wrapper de `databricks ... -o json`

ESTADOS_FINAIS = {"COMPLETED", "FAILED", "CANCELLED", "QUERY_RESULT_EXPIRED"}


def sem_acento(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    return "".join(c for c in s if not unicodedata.combining(c)).casefold().strip()


def achar_espaco(titulo: str, profile: str) -> str:
    r = cli(["genie", "list-spaces"], profile)
    espacos = r if isinstance(r, list) else r.get("spaces", [])
    exatos = [e for e in espacos if e.get("title") == titulo] or [
        e for e in espacos if sem_acento(e.get("title", "")) == sem_acento(titulo)
    ]
    if not exatos:
        sys.exit(
            "espaco nao encontrado. Titulos disponiveis:\n  "
            + "\n  ".join(e.get("title", "") for e in espacos)
        )
    if len(exatos) > 1:
        sys.exit(
            f"{len(exatos)} espacos com o titulo {titulo!r}: "
            + ", ".join(e.get("space_id", "?") for e in exatos)
        )
    return exatos[0]["space_id"]


def perguntar(space_id: str, pergunta: str, profile: str, timeout: int = 300) -> tuple:
    r = cli(["genie", "start-conversation", space_id, pergunta, "--no-wait"], profile)
    conversa = r.get("conversation_id") or r["conversation"]["id"]
    mensagem = r.get("message_id") or r["message"]["id"]
    limite = time.time() + timeout
    while True:
        m = cli(["genie", "get-message", space_id, conversa, mensagem], profile)
        if m.get("status") in ESTADOS_FINAIS:
            return conversa, mensagem, m
        if time.time() > limite:
            return conversa, mensagem, m
        time.sleep(3)


def resposta(space_id, conversa, mensagem, m, profile) -> tuple:
    """Devolve (texto, sql, colunas, linhas) de uma mensagem terminada."""
    textos, sql, colunas, linhas = [], None, [], []
    for a in m.get("attachments") or []:
        if (a.get("text") or {}).get("content"):
            textos.append(a["text"]["content"])
        if a.get("query"):
            sql = a["query"].get("query")
            if a["query"].get("description"):
                textos.append(a["query"]["description"])
            try:
                r = cli(
                    ["genie", "get-message-attachment-query-result",
                     space_id, conversa, mensagem, a["attachment_id"]],
                    profile,
                )
                st = r.get("statement_response", {})
                colunas = [c["name"] for c in st.get("manifest", {}).get("schema", {}).get("columns", [])]
                linhas = st.get("result", {}).get("data_array") or []
            except Exception as erro:  # noqa: BLE001
                textos.append(f"(nao foi possivel ler o resultado: {str(erro)[:120]})")
    return "\n".join(t for t in textos if t), sql, colunas, linhas


# --------------------------------------------------------------------- #
# verificacao do benchmark
# --------------------------------------------------------------------- #
def numeros(palheiro: str) -> list[float]:
    """Todos os numeros do palheiro, nas duas notacoes (1.234,56 e 1234.56)."""
    achados = []
    for cru in re.findall(r"-?\d[\d.,]*", palheiro):
        cru = cru.rstrip(".,")
        if not cru:
            continue
        candidatos = {cru.replace(".", "").replace(",", ".")}  # 1.234,56 -> 1234.56
        candidatos.add(cru.replace(",", ""))                   # 1,234.56 -> 1234.56
        candidatos.add(cru.replace(",", "."))                  # 0,92     -> 0.92
        for c in candidatos:
            try:
                achados.append(float(c))
            except ValueError:
                pass
    return achados


def tem_numero(palheiro: str, alvo: float, tolerancia: float) -> bool:
    margem = abs(alvo) * tolerancia if tolerancia else 0.0
    return any(abs(n - alvo) <= margem for n in numeros(palheiro))


def verificar(item: dict, texto: str, colunas: list, linhas: list) -> tuple[bool, str]:
    achatado = " | ".join(str(c) for linha in linhas for c in linha)
    palheiro = f"{texto}\n{' '.join(colunas)}\n{achatado}"
    palheiro_sem_acento = sem_acento(palheiro)
    como = item["como_verificar"]
    esperado = item.get("esperado")
    tol = item.get("tolerancia", 0.02)

    if como == "numero":
        faltando = [e for e in esperado if not tem_numero(palheiro, float(e), tol)]
        return (not faltando), ("" if not faltando else f"nao achei {faltando}")
    if como == "numero_qualquer":
        if any(tem_numero(palheiro, float(e), tol) for e in esperado):
            return True, ""
        return False, f"nenhum de {esperado}"
    if como == "contem":
        faltando = [e for e in esperado if sem_acento(str(e)) not in palheiro_sem_acento]
        return (not faltando), ("" if not faltando else f"nao achei {faltando}")
    if como == "conjunto":
        faltando = [e for e in esperado if sem_acento(str(e)) not in palheiro_sem_acento]
        proibido = [e for e in item.get("nao_esperado", [])
                    if sem_acento(str(e)) in palheiro_sem_acento]
        if faltando or proibido:
            return False, f"faltando {faltando} proibido {proibido}".strip()
        return True, ""
    if como == "linhas":
        return len(linhas) == int(esperado), f"{len(linhas)} linhas, esperava {esperado}"
    if como == "distinto":
        if not linhas:
            return False, "nenhuma linha"
        primeira = [str(l[0]) for l in linhas]
        return len(primeira) == len(set(primeira)), "valor repetido na primeira coluna"
    return False, f"verificador desconhecido: {como}"


def rodar_benchmark(space_id: str, caminho: Path, profile: str, minimo: int = 16) -> int:
    itens = json.loads(caminho.read_text(encoding="utf-8"))
    acertos, erros = 0, []
    for i, item in enumerate(itens, 1):
        conversa, mensagem, m = perguntar(space_id, item["pergunta"], profile)
        if m.get("status") != "COMPLETED":
            erros.append((i, item, f"status {m.get('status')}", None, ""))
            print(f"[{i:02d}/{len(itens)}] ERROU  status {m.get('status')}")
            continue
        texto, sql, colunas, linhas = resposta(space_id, conversa, mensagem, m, profile)
        ok, motivo = verificar(item, texto, colunas, linhas)
        acertos += ok
        print(f"[{i:02d}/{len(itens)}] {'ok   ' if ok else 'ERROU'}  {item['pergunta'][:62]}"
              + ("" if ok else f"\n           {motivo}"))
        if not ok:
            erros.append((i, item, motivo, sql, " | ".join(str(c) for c in (linhas[0] if linhas else []))))

    print(f"\n{'=' * 64}\nplacar: {acertos}/{len(itens)}\n{'=' * 64}")
    for i, item, motivo, sql, primeira in erros:
        print(f"\n[{i:02d}] {item['pergunta']}")
        print(f"     esperado ({item['como_verificar']}): {item.get('esperado')}")
        print(f"     motivo: {motivo}")
        if item.get("porque"):
            print(f"     por que esta pergunta existe: {item['porque']}")
        if primeira:
            print(f"     1a linha do resultado: {primeira[:160]}")
        if sql:
            print("     SQL do Genie:")
            for linha in sql.splitlines()[:14]:
                print(f"       {linha}")
    return 0 if acertos >= minimo else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="comando", required=True)

    p1 = sub.add_parser("perguntar")
    p1.add_argument("espaco")
    p1.add_argument("pergunta")
    p1.add_argument("--profile", required=True)

    p2 = sub.add_parser("benchmark")
    p2.add_argument("espaco")
    p2.add_argument("arquivo")
    p2.add_argument("--profile", required=True)
    p2.add_argument("--minimo", type=int, default=16)

    args = ap.parse_args()
    space_id = achar_espaco(args.espaco, args.profile)

    if args.comando == "perguntar":
        print(f"espaco  : {args.espaco}  ({space_id})")
        print(f"pergunta: {args.pergunta}\n")
        conversa, mensagem, m = perguntar(space_id, args.pergunta, args.profile)
        print(f"estado  : {m.get('status')}\n")
        texto, sql, colunas, linhas = resposta(space_id, conversa, mensagem, m, args.profile)
        if texto:
            print(texto, "\n")
        if sql:
            print("SQL que o Genie escreveu:")
            for linha in sql.splitlines():
                print(f"  {linha}")
            print()
        if colunas:
            print(" | ".join(colunas))
            print("-" * 70)
            for linha in linhas[:30]:
                print(" | ".join("" if c is None else str(c) for c in linha))
            if len(linhas) > 30:
                print(f"... e mais {len(linhas) - 30} linha(s)")
        return 0

    return rodar_benchmark(space_id, Path(args.arquivo), args.profile, args.minimo)


if __name__ == "__main__":
    raise SystemExit(main())
