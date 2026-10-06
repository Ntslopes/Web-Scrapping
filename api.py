"""
API FastAPI — IBJJF Ranking

Disponibiliza os dados coletados pelo crawler (MongoDB) e alimenta o dashboard.

Executar:
    uvicorn api:app --reload

Documentação interativa (Swagger): http://127.0.0.1:8000/docs
"""

import re
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from database import close_connection, get_db

# Mesmos campos que identificam um atleta no crawler
KEY_FIELDS = ["name", "ranking_type", "age_category", "gender", "belt"]

# Campos permitidos para ordenação (evita ordenar por campo arbitrário)
SORT_FIELDS = {
    "rank": "rank",
    "points": "points",
    "name": "name",
    "last_collected_at": "last_collected_at",
}


# ==========================================
# CICLO DE VIDA
# ==========================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    close_connection()


app = FastAPI(
    title="IBJJF Ranking API",
    description=(
        "API que disponibiliza os dados do ranking de atletas da IBJJF "
        "coletados pelo crawler e armazenados no MongoDB."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

# Libera o acesso do dashboard (que roda em outra porta/origem)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)


# ==========================================
# MODELOS (documentação das respostas)
# ==========================================

class Source(BaseModel):
    site: Optional[str] = None
    url: Optional[str] = None
    page: Optional[int] = None


class Athlete(BaseModel):
    id: str
    name: str
    photo: Optional[str] = None
    points: Optional[float] = None
    rank: Optional[int] = None
    profile_url: Optional[str] = None
    ranking_type: Optional[str] = None
    age_category: Optional[str] = None
    gender: Optional[str] = None
    belt: Optional[str] = None
    source: Optional[Source] = None
    first_collected_at: Optional[datetime] = None
    last_collected_at: Optional[datetime] = None


class AthleteList(BaseModel):
    total: int
    page: int
    page_size: int
    total_pages: int
    items: list[Athlete]


class HistoryEntry(BaseModel):
    collected_at: datetime
    rank: Optional[int] = None
    points: Optional[float] = None


# ==========================================
# FUNÇÕES AUXILIARES
# ==========================================

def to_utc(value):
    """O MongoDB devolve datas 'ingênuas'; marcamos como UTC."""
    if isinstance(value, datetime) and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def serialize(doc: dict) -> dict:
    """Converte um documento do MongoDB em algo serializável em JSON."""
    doc = dict(doc)
    doc["id"] = str(doc.pop("_id"))

    for key, value in doc.items():
        doc[key] = to_utc(value)

    return doc


def parse_object_id(value: str) -> ObjectId:
    try:
        return ObjectId(value)
    except (InvalidId, TypeError):
        raise HTTPException(status_code=422, detail="ID inválido.")


class AthleteFilters:
    """
    Filtros compartilhados entre listagem, estatísticas e dashboard.
    Usados como dependência: Depends(AthleteFilters).
    """

    def __init__(
        self,
        search: Optional[str] = Query(
            None, description="Busca parcial pelo nome do atleta"
        ),
        gender: Optional[str] = Query(None, description="Ex.: male, female"),
        belt: Optional[str] = Query(None, description="Ex.: black"),
        age_category: Optional[str] = Query(None, description="Ex.: adult"),
        ranking_type: Optional[str] = Query(
            None, description="Ex.: ranking-geral-gi"
        ),
        min_points: Optional[float] = Query(None, ge=0),
        max_points: Optional[float] = Query(None, ge=0),
        min_rank: Optional[int] = Query(None, ge=1),
        max_rank: Optional[int] = Query(None, ge=1),
    ):
        self.search = search
        self.gender = gender
        self.belt = belt
        self.age_category = age_category
        self.ranking_type = ranking_type
        self.min_points = min_points
        self.max_points = max_points
        self.min_rank = min_rank
        self.max_rank = max_rank

    def to_query(self) -> dict:
        query: dict = {}

        if self.search:
            query["name"] = {
                "$regex": re.escape(self.search.strip()),
                "$options": "i",
            }

        for field in ("gender", "belt", "age_category", "ranking_type"):
            value = getattr(self, field)
            if value:
                query[field] = value

        if self.min_points is not None or self.max_points is not None:
            points = {}
            if self.min_points is not None:
                points["$gte"] = self.min_points
            if self.max_points is not None:
                points["$lte"] = self.max_points
            query["points"] = points

        if self.min_rank is not None or self.max_rank is not None:
            rank = {}
            if self.min_rank is not None:
                rank["$gte"] = self.min_rank
            if self.max_rank is not None:
                rank["$lte"] = self.max_rank
            query["rank"] = rank

        return query


# ==========================================
# ENDPOINTS BÁSICOS
# ==========================================

@app.get("/", tags=["Geral"])
def root():
    """Status da API e lista de endpoints principais."""
    return {
        "api": "IBJJF Ranking API",
        "status": "online",
        "docs": "/docs",
        "endpoints": [
            "/athletes",
            "/athletes/{id}",
            "/athletes/{id}/history",
            "/filters",
            "/stats",
            "/dashboard",
        ],
    }


@app.get("/health", tags=["Geral"])
def health(db=Depends(get_db)):
    """Verifica a conexão com o MongoDB."""
    try:
        db.command("ping")
    except Exception as error:
        raise HTTPException(status_code=503, detail=f"MongoDB indisponível: {error}")
    return {"status": "ok", "database": db.name}


# ==========================================
# ATLETAS: LISTAR, FILTRAR/BUSCAR, CONSULTAR
# ==========================================

@app.get("/athletes", response_model=AthleteList, tags=["Atletas"])
def list_athletes(
    filters: AthleteFilters = Depends(),
    sort_by: str = Query("rank", description="rank, points, name ou last_collected_at"),
    order: str = Query("asc", pattern="^(asc|desc)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db=Depends(get_db),
):
    """
    Lista os atletas com paginação, ordenação, filtros e busca por nome.

    Exemplos:
    - `/athletes?search=silva`
    - `/athletes?min_points=500&sort_by=points&order=desc`
    - `/athletes?gender=male&belt=black&page=2`
    """
    if sort_by not in SORT_FIELDS:
        raise HTTPException(
            status_code=422,
            detail=f"sort_by inválido. Use: {', '.join(SORT_FIELDS)}",
        )

    query = filters.to_query()
    direction = 1 if order == "asc" else -1

    total = db["athletes"].count_documents(query)

    cursor = (
        db["athletes"]
        .find(query)
        .sort([(SORT_FIELDS[sort_by], direction), ("_id", 1)])
        .skip((page - 1) * page_size)
        .limit(page_size)
    )

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size,
        "items": [serialize(doc) for doc in cursor],
    }


@app.get("/filters", tags=["Atletas"])
def available_filters(db=Depends(get_db)):
    """Valores distintos disponíveis para filtros (útil para o dashboard)."""
    athletes = db["athletes"]

    return {
        "gender": sorted(athletes.distinct("gender")),
        "belt": sorted(athletes.distinct("belt")),
        "age_category": sorted(athletes.distinct("age_category")),
        "ranking_type": sorted(athletes.distinct("ranking_type")),
    }


@app.get("/athletes/{athlete_id}", response_model=Athlete, tags=["Atletas"])
def get_athlete(athlete_id: str, db=Depends(get_db)):
    """Consulta um atleta específico pelo ID."""
    doc = db["athletes"].find_one({"_id": parse_object_id(athlete_id)})

    if not doc:
        raise HTTPException(status_code=404, detail="Atleta não encontrado.")

    return serialize(doc)


@app.get(
    "/athletes/{athlete_id}/history",
    response_model=list[HistoryEntry],
    tags=["Atletas"],
)
def get_athlete_history(athlete_id: str, db=Depends(get_db)):
    """Evolução de posição e pontos do atleta ao longo das coletas."""
    athlete = db["athletes"].find_one({"_id": parse_object_id(athlete_id)})

    if not athlete:
        raise HTTPException(status_code=404, detail="Atleta não encontrado.")

    key = {k: athlete.get(k) for k in KEY_FIELDS}

    history = (
        db["ranking_history"]
        .find(key, {"_id": 0, "collected_at": 1, "rank": 1, "points": 1})
        .sort("collected_at", 1)
    )

    return [
        {**entry, "collected_at": to_utc(entry["collected_at"])}
        for entry in history
    ]


# ==========================================
# ESTATÍSTICAS
# ==========================================

@app.get("/stats", tags=["Estatísticas"])
def get_stats(filters: AthleteFilters = Depends(), db=Depends(get_db)):
    """Estatísticas gerais sobre os dados coletados."""
    query = filters.to_query()

    summary = list(
        db["athletes"].aggregate([
            {"$match": query},
            {
                "$group": {
                    "_id": None,
                    "total": {"$sum": 1},
                    "total_points": {"$sum": "$points"},
                    "avg_points": {"$avg": "$points"},
                    "max_points": {"$max": "$points"},
                    "min_points": {"$min": "$points"},
                    "first_collected_at": {"$min": "$first_collected_at"},
                    "last_collected_at": {"$max": "$last_collected_at"},
                }
            },
        ])
    )
    summary = summary[0] if summary else {}

    leader = db["athletes"].find_one(
        {**query, "rank": {"$ne": None}}, sort=[("rank", 1)]
    )

    collections_count = len(db["ranking_history"].distinct("collected_at"))

    avg_points = summary.get("avg_points")

    return {
        "total_athletes": summary.get("total", 0),
        "total_snapshots": db["ranking_history"].count_documents({}),
        "total_collections": collections_count,
        "points": {
            "total": summary.get("total_points"),
            "average": round(avg_points, 2) if avg_points is not None else None,
            "max": summary.get("max_points"),
            "min": summary.get("min_points"),
        },
        "leader": (
            {
                "id": str(leader["_id"]),
                "name": leader["name"],
                "points": leader.get("points"),
                "rank": leader.get("rank"),
            }
            if leader
            else None
        ),
        "first_collected_at": to_utc(summary.get("first_collected_at")),
        "last_collected_at": to_utc(summary.get("last_collected_at")),
    }


# ==========================================
# DADOS PARA O DASHBOARD
# ==========================================

@app.get("/dashboard", tags=["Dashboard"])
def get_dashboard(
    filters: AthleteFilters = Depends(),
    top: int = Query(10, ge=1, le=50, description="Tamanho do Top N"),
    buckets: int = Query(5, ge=2, le=12, description="Faixas do histograma"),
    db=Depends(get_db),
):
    """
    Dados prontos para alimentar o dashboard:
    - cards: indicadores principais
    - top_athletes: Top N por pontuação (gráfico de barras)
    - points_distribution: histograma de pontuação
    - collections_timeline: evolução por coleta (gráfico de linha)
    """
    query = filters.to_query()
    athletes = db["athletes"]

    # --- Indicadores (cards) ---
    stats = get_stats(filters, db)

    cards = {
        "total_athletes": stats["total_athletes"],
        "total_collections": stats["total_collections"],
        "average_points": stats["points"]["average"],
        "max_points": stats["points"]["max"],
        "leader": stats["leader"]["name"] if stats["leader"] else None,
        "last_collected_at": stats["last_collected_at"],
    }

    # --- Top N atletas por pontuação ---
    top_athletes = [
        {
            "id": str(doc["_id"]),
            "name": doc["name"],
            "rank": doc.get("rank"),
            "points": doc.get("points"),
        }
        for doc in athletes.find({**query, "points": {"$ne": None}})
        .sort("points", -1)
        .limit(top)
    ]

    # --- Distribuição de pontuação (histograma) ---
    distribution = []
    has_points = {**query, "points": {"$ne": None}}

    if athletes.count_documents(has_points) > 0:
        for bucket in athletes.aggregate([
            {"$match": has_points},
            {
                "$bucketAuto": {
                    "groupBy": "$points",
                    "buckets": buckets,
                }
            },
        ]):
            distribution.append({
                "min": bucket["_id"]["min"],
                "max": bucket["_id"]["max"],
                "count": bucket["count"],
            })

    # --- Evolução por coleta ---
    # O histórico guarda os mesmos campos do atleta, então os filtros valem aqui também
    timeline = [
        {
            "collected_at": to_utc(item["_id"]),
            "athletes": item["athletes"],
            "average_points": (
                round(item["average_points"], 2)
                if item["average_points"] is not None
                else None
            ),
        }
        for item in db["ranking_history"].aggregate([
            {"$match": query},
            {
                "$group": {
                    "_id": "$collected_at",
                    "athletes": {"$sum": 1},
                    "average_points": {"$avg": "$points"},
                }
            },
            {"$sort": {"_id": 1}},
        ])
    ]

    return {
        "cards": cards,
        "top_athletes": top_athletes,
        "points_distribution": distribution,
        "collections_timeline": timeline,
    }