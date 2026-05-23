"""Cross-source player matching: PFF ↔ StatsBomb (or any other source).

Match strategy
--------------
1. Normalize names: lowercase, strip diacritics, drop punctuation, collapse spaces.
2. Exact normalized-name match → confidence 1.0.
3. Last-name + first-initial match → confidence 0.85.
4. Pure last-name match (only if unique) → confidence 0.7.
5. Manual override map handles known nickname / formal-name mismatches.

The result is a DataFrame: pff_player_id, statsbomb_player_id, name_pff, name_sb,
match_strategy, confidence.
"""
from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from pathlib import Path

import pandas as pd


# Manual override: PFF "nickname" → StatsBomb canonical name.
# These cover the obvious culture-of-naming differences across providers.
MANUAL_OVERRIDES: dict[str, str] = {
    "Memphis Depay": "Memphis Depay",
    "Cristiano Ronaldo": "Cristiano Ronaldo dos Santos Aveiro",
    "Kylian Mbappé": "Kylian Mbappé Lottin",
    "Kylian Mbappe": "Kylian Mbappé Lottin",
    "Bruno Fernandes": "Bruno Miguel Borges Fernandes",
    "Pepe": "Képler Laveran Lima Ferreira",
    "Rúben Dias": "Rúben Santos Gato Alves Dias",
    "Diogo Dalot": "José Diogo Dalot Teixeira",
    "Vitinha": "Vítor Machado Ferreira",
    "Bernardo Silva": "Bernardo Mota Veiga de Carvalho e Silva",
    "Bruno Guimarães": "Bruno Guimarães Rodriguez Moura",
    "Casemiro": "Carlos Henrique Venancio Casimiro",
    "Marquinhos": "Marcos Aoás Corrêa",
    "Vinícius Junior": "Vinícius José Paixão de Oliveira Júnior",
    "Vinicius Junior": "Vinícius José Paixão de Oliveira Júnior",
    "Richarlison": "Richarlison de Andrade",
    "Neymar": "Neymar da Silva Santos Júnior",
    "Antony": "Antony Matheus dos Santos",
    "Fred": "Frederico Rodrigues de Paula Santos",
    "Rodrygo": "Rodrygo Silva de Goes",
    "Thiago Silva": "Thiago Emiliano da Silva",
    "Alisson": "Alisson Ramses Becker",
    "Ederson": "Ederson Santana de Moraes",
    "Pedri": "Pedro González López",
    "Gavi": "Pablo Martín Páez Gavira",
    "Rodri": "Rodrigo Hernández Cascante",
    "Ferran Torres": "Ferran Torres García",
    "Dani Olmo": "Daniel Olmo Carvajal",
    "Alvaro Morata": "Álvaro Morata Martín",
    "Ansu Fati": "Anssumane Fati",
    "Eric García": "Eric García Martret",
    "Aymeric Laporte": "Aymeric Jean Louis Gerard Alphonse Laporte",
    "Antoine Griezmann": "Antoine Griezmann",
    "Aurélien Tchouaméni": "Aurélien Djani Tchouaméni",
    "Aurelien Tchouameni": "Aurélien Djani Tchouaméni",
    "Theo Hernandez": "Théo Bernard François Hernández",
    "Théo Hernandez": "Théo Bernard François Hernández",
    "Achraf Hakimi": "Achraf Hakimi Mouh",
    "Jude Bellingham": "Jude Victor William Bellingham",
    "Bukayo Saka": "Bukayo Ayoyinka Temidayo Saka",
    "Joao Felix": "João Félix Sequeira",
    "João Félix": "João Félix Sequeira",
    "Joao Cancelo": "João Pedro Cavaco Cancelo",
    "João Cancelo": "João Pedro Cavaco Cancelo",
    "Otavio": "Otávio Edmilson da Silva Monteiro",
    "Goncalo Ramos": "Gonçalo Matias Ramos",
    "Gonçalo Ramos": "Gonçalo Matias Ramos",
    "Andre": "André de Almeida",
    "Raphael Guerreiro": "Raphaël Adelino José Guerreiro",
    "Raphael Varane": "Raphaël Xavier Varane",
}


def normalize_name(name: str) -> str:
    """Lowercase + strip diacritics + drop punctuation/spaces."""
    if not name:
        return ""
    s = unicodedata.normalize("NFKD", str(name))
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = s.lower()
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def last_name_key(name: str) -> str:
    parts = normalize_name(name).split()
    return parts[-1] if parts else ""


def first_initial(name: str) -> str:
    parts = normalize_name(name).split()
    return parts[0][:1] if parts else ""


def build_player_match(
    pff_players: pd.DataFrame,
    sb_players: pd.DataFrame,
) -> pd.DataFrame:
    """Match every PFF player to a StatsBomb player by name.

    pff_players: columns (pff_player_id, name)
    sb_players: columns (statsbomb_player_id, name)
    """
    # Build normalized indices on the SB side
    sb_by_norm: dict[str, list[tuple[int, str]]] = defaultdict(list)
    sb_by_last: dict[str, list[tuple[int, str]]] = defaultdict(list)
    sb_by_last_initial: dict[tuple[str, str], list[tuple[int, str]]] = defaultdict(list)
    for r in sb_players.itertuples():
        norm = normalize_name(r.name)
        sb_by_norm[norm].append((int(r.statsbomb_player_id), r.name))
        ln = last_name_key(r.name)
        sb_by_last[ln].append((int(r.statsbomb_player_id), r.name))
        fi = first_initial(r.name)
        if ln and fi:
            sb_by_last_initial[(ln, fi)].append((int(r.statsbomb_player_id), r.name))

    out: list[dict] = []
    for r in pff_players.itertuples():
        pff_id = int(r.pff_player_id)
        pff_name = r.name
        # 1. Manual override
        override = MANUAL_OVERRIDES.get(pff_name)
        if override:
            cands = sb_by_norm.get(normalize_name(override), [])
            if cands:
                sid, sname = cands[0]
                out.append({"pff_player_id": pff_id, "statsbomb_player_id": sid,
                            "name_pff": pff_name, "name_sb": sname,
                            "strategy": "override", "confidence": 0.95})
                continue
        # 2. Exact normalized
        norm = normalize_name(pff_name)
        cands = sb_by_norm.get(norm, [])
        if len(cands) == 1:
            sid, sname = cands[0]
            out.append({"pff_player_id": pff_id, "statsbomb_player_id": sid,
                        "name_pff": pff_name, "name_sb": sname,
                        "strategy": "exact", "confidence": 1.0})
            continue
        # 3. Last + first initial
        ln = last_name_key(pff_name); fi = first_initial(pff_name)
        cands = sb_by_last_initial.get((ln, fi), [])
        if len(cands) == 1:
            sid, sname = cands[0]
            out.append({"pff_player_id": pff_id, "statsbomb_player_id": sid,
                        "name_pff": pff_name, "name_sb": sname,
                        "strategy": "last+initial", "confidence": 0.85})
            continue
        # 4. Pure last name
        cands = sb_by_last.get(ln, [])
        if len(cands) == 1:
            sid, sname = cands[0]
            out.append({"pff_player_id": pff_id, "statsbomb_player_id": sid,
                        "name_pff": pff_name, "name_sb": sname,
                        "strategy": "last_only", "confidence": 0.7})
            continue

    return pd.DataFrame(out)
