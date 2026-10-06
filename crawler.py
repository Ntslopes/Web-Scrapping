import re
import time
from datetime import datetime, timezone
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from pymongo import UpdateOne
from pymongo.errors import OperationFailure

from database import get_db, close_connection


# ==========================================
# CONFIGURAÇÕES
# ==========================================

DOMAIN = "https://ibjjf.com"
URL = f"{DOMAIN}/2026-athletes-ranking"

HEADERS = {"User-Agent": "Mozilla/5.0"}

PARAMETERS = {
    "filters[s]": "ranking-geral-gi",
    "filters[ranking_category]": "adult",
    "filters[gender]": "male",
    "filters[belt]": "black",
    "filters[weight]": "",
    "filters[search]": "",
    "commit": "Search",
    "page": 1,
}

MAX_PAGES = 5
REQUEST_DELAY = 1.5

# Campos que identificam um atleta de forma única
KEY_FIELDS = ["name", "ranking_type", "age_category", "gender", "belt"]


# ==========================================
# REQUISIÇÃO
# ==========================================

def get_page_content(url, headers, parameters):
    response = requests.get(
        url, headers=headers, params=parameters, timeout=30
    )
    response.raise_for_status()
    return BeautifulSoup(response.text, "html.parser")


# ==========================================
# TRATAMENTO DOS DADOS
# ==========================================

def parse_rank(value):
    match = re.search(r"\d+", value or "")
    return int(match.group()) if match else None


def parse_points(value):
    value = re.sub(r"[^\d,.\-]", "", (value or "").strip())

    if not value:
        return None

    if "," in value and "." in value:
        value = value.replace(".", "").replace(",", ".")
    elif "," in value:
        value = value.replace(",", ".")
    elif value.count(".") > 1:
        value = value.replace(".", "")

    try:
        number = float(value)
        return int(number) if number.is_integer() else number
    except ValueError:
        return None


# ==========================================
# EXTRAÇÃO DOS ATLETAS
# ==========================================

def parse_athletes(soup, page):
    table = soup.find("table")

    if not table:
        print("Tabela não encontrada.")
        return []

    athletes = []

    for row in table.find_all("tr"):
        photo_cell = row.find("td", class_="photo reduced")
        name_cell = row.find("td", class_="name-academy")
        points_cell = row.find("td", class_="pontuation")
        rank_cell = row.find("td", class_="position")

        if not all([photo_cell, name_cell, points_cell, rank_cell]):
            continue

        # Nome
        name_container = name_cell.find("div", class_="name")
        if not name_container:
            continue

        name_tag = name_container.find("a")
        if not name_tag:
            continue

        name = name_tag.get_text(strip=True)
        if not name:
            continue

        # Link do perfil
        href = name_tag.get("href")
        profile_url = urljoin(DOMAIN, href) if href else None

        # Foto
        photo = None
        img = photo_cell.find("img")
        if img:
            photo = (
                img.get("src")
                or img.get("data-src")
                or img.get("data-lazy-src")
            )
            if photo:
                photo = urljoin(DOMAIN, photo)

        # Pontuação e posição
        points = parse_points(points_cell.get_text(strip=True))
        rank = parse_rank(rank_cell.get_text(strip=True))

        if rank is None:
            continue

        athletes.append({
            "name": name,
            "photo": photo,
            "points": points,
            "rank": rank,
            "profile_url": profile_url,
            # categoria (faz parte da chave de unicidade)
            "ranking_type": PARAMETERS["filters[s]"],
            "age_category": PARAMETERS["filters[ranking_category]"],
            "gender": PARAMETERS["filters[gender]"],
            "belt": PARAMETERS["filters[belt]"],
            # de onde o dado veio
            "source": {
                "site": "ibjjf.com",
                "url": URL,
                "page": page,
            },
        })

    return athletes


# ==========================================
# SALVAR NO MONGODB
# ==========================================

def save_athletes(db, athletes, collected_at):
    """
    - athletes: estado atual (sem duplicados, atualizado a cada coleta)
    - ranking_history: um registro por atleta a cada coleta (nunca sobrescrito)
    """
    if not athletes:
        return 0

    operations = []
    snapshots = []

    for athlete in athletes:
        key = {k: athlete[k] for k in KEY_FIELDS}

        operations.append(UpdateOne(
            key,
            {
                "$set": {**athlete, "last_collected_at": collected_at},
                "$setOnInsert": {"first_collected_at": collected_at},
            },
            upsert=True,
        ))

        snapshots.append({**athlete, "collected_at": collected_at})

    result = db["athletes"].bulk_write(operations, ordered=False)
    db["ranking_history"].insert_many(snapshots)

    return result.upserted_count + result.modified_count


def setup_indexes(db):
    athletes = db["athletes"]

    # Remove o índice antigo (só "name"), se existir
    try:
        athletes.drop_index("name_1")
    except OperationFailure:
        pass

    athletes.create_index([(k, 1) for k in KEY_FIELDS], unique=True)

    db["ranking_history"].create_index(
        [("collected_at", -1), ("name", 1)]
    )


# ==========================================
# EXECUÇÃO
# ==========================================

def main():
    total_athletes = 0

    try:
        db = get_db()
        db.command("ping")

        print("=" * 50)
        print("IBJJF CRAWLER")
        print("=" * 50)
        print("MongoDB conectado!")
        print(f"Database: {db.name}")
        print("Collections: athletes, ranking_history")
        print("-" * 50)

        setup_indexes(db)

        # Data/hora única para toda a execução
        collected_at = datetime.now(timezone.utc)

        for page in range(1, MAX_PAGES + 1):
            print(f"Buscando página {page}...")

            PARAMETERS["page"] = page

            soup = get_page_content(URL, HEADERS, PARAMETERS)
            athletes = parse_athletes(soup, page)

            if not athletes:
                print("Nenhum atleta encontrado. Finalizando crawler...")
                break

            saved = save_athletes(db, athletes, collected_at)
            total_athletes += len(athletes)

            print(f"Atletas encontrados: {len(athletes)}")
            print(f"Atletas inseridos/atualizados: {saved}")
            print("-" * 50)

            time.sleep(REQUEST_DELAY)

        print()
        print("=" * 50)
        print("CRAWLER FINALIZADO")
        print("=" * 50)
        print(f"Total processado: {total_athletes}")
        print(f"Atletas no MongoDB: {db['athletes'].count_documents({})}")
        print(f"Registros no histórico: {db['ranking_history'].count_documents({})}")

    except requests.RequestException as error:
        print(f"Erro na requisição: {error}")

    except Exception as error:
        print(f"Erro: {error}")

    finally:
        close_connection()


if __name__ == "__main__":
    main()