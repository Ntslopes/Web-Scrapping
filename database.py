import os

from pymongo import MongoClient

try:
    # Carrega o arquivo .env, se existir (pip install python-dotenv)
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

DB_NAME = "ibjjfDB"

_client = None


def get_db():
    """Retorna o database, criando a conexão na primeira chamada."""
    global _client

    if _client is None:
        uri = os.environ.get("MONGODB_URI")
        if not uri:
            raise RuntimeError(
                "Variável de ambiente MONGODB_URI não definida."
            )
        _client = MongoClient(uri, serverSelectionTimeoutMS=10000)

    return _client[DB_NAME]


def close_connection():
    """Fecha a conexão com o MongoDB."""
    global _client

    if _client is not None:
        _client.close()
        _client = None