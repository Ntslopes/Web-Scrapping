from pymongo import MongoClient

# String de conexão do Atlas (Connect > Drivers)
uri = "mongodb+srv://matheusllima2506_db_user:MkRTztQkd8YvM7oY@clusterdolopes.uxpuoi2.mongodb.net/?appName=clusterdolopes"
client = MongoClient(uri)

# Isso ainda NÃO cria nada no servidor
db = client["meu_database"]
colecao = db["minha_colecao"]

# Aqui sim: o database e a coleção são criados automaticamente
resultado = colecao.insert_one({"nome": "Maria", "idade": 30})
print("Inserido com id:", resultado.inserted_id)