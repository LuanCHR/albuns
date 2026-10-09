import json
from pathlib import Path

termo = input("Parte do nome da playlist a remover: ").strip().lower()
arquivo = Path("docs/data/playlists.json")
dados = json.loads(arquivo.read_text(encoding="utf-8"))

fora = [a for a in dados["albums"] if termo in a["title"].lower()]
dados["albums"] = [a for a in dados["albums"] if a not in fora]
arquivo.write_text(json.dumps(dados, ensure_ascii=False, indent=1), encoding="utf-8")

for a in fora:
    for capa in Path("docs/covers").glob(a["id"] + ".*"):
        capa.unlink()
    print("Removida:", a["title"])
print("Total removido:", len(fora))