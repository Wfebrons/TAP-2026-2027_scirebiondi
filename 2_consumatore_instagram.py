import json
import time
import redis
from elasticsearch import Elasticsearch

# Configurazione connessioni e servizi
HOST_REDIS = 'localhost'
PORTA_REDIS = 6379
NOME_CODA_REDIS = "coda_instagram"

URL_ELASTICSEARCH = "http://localhost:9200"
NOME_INDICE_ES = "instagram_cta"

connessione_redis = redis.Redis(host=HOST_REDIS, port=PORTA_REDIS, db=0, decode_responses=True)
es_client = Elasticsearch(URL_ELASTICSEARCH)


def salva_post_su_elasticsearch(dati_post):
    """Prepara il documento con timestamp formattato e lo salva su Elasticsearch."""
    documento = {
        "@timestamp": dati_post["data_pubblicazione"],
        "id_post": dati_post["id"],
        "testo": dati_post["testo"],
        "link_immagine": dati_post["url_immagine"],
        "link_post": dati_post["link_post"]
    }
    
    try:
        # Usa l'ID del post come document ID su ES per evitare duplicati
        es_client.index(index=NOME_INDICE_ES, id=dati_post["id"], document=documento)
        print(f"✅ Indicizzato su Elasticsearch -> Post ID: {dati_post['id']}")
    except Exception as errore:
        print(f"⚠️ Errore di scrittura su Elasticsearch: {errore}")


def elabora_singolo_post(dati_json_raw):
    """Parsing del payload JSON proveniente da Redis e invio al gestore ES."""
    try:
        dati_post = json.loads(dati_json_raw)
        salva_post_su_elasticsearch(dati_post)
    except Exception as errore:
        print(f"⚠️ Errore di decodifica JSON: {errore}")


def avvia_consumatore_instagram():
    """Loop di ascolto continuo sulla coda Redis."""
    print("In attesa di post da Redis...")
    
    while True:
        try:
            elemento = connessione_redis.blpop(NOME_CODA_REDIS, timeout=5)
            
            if elemento:
                _, dati_json = elemento
                elabora_singolo_post(dati_json)
            else:
                time.sleep(2)
                
        except redis.exceptions.TimeoutError:
            continue
        except Exception as errore:
            print(f"⚠️ Errore imprevisto nel consumatore Instagram: {errore}")
            time.sleep(2)


if __name__ == "__main__":
    avvia_consumatore_instagram()
