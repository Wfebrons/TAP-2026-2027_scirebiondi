import json
import time
import requests
import redis
import hashlib
from datetime import datetime, timezone
from elasticsearch import Elasticsearch

# Configurazione servizi e connessioni
es_client = Elasticsearch("http://localhost:9200")
NOME_INDICE_ES = "voli_analizzati"

connessione_redis = redis.Redis(host='localhost', port=6379, db=0, socket_timeout=None)
NOME_CODA_REDIS = "coda_voli_catania"

OLLAMA_URL = "http://127.0.0.1:11434/api/generate"
NOME_MODELLO_LLM = "llama3.2:1b"


def recupera_storico_volo(numero_volo, destinazione):
    """Interroga Elasticsearch per recuperare fino a 5 precedenti del volo o della rotta."""
    query_storico = {
        "size": 5,
        "query": {
            "bool": {
                "should": [
                    { "match": { "numero_volo": numero_volo } },
                    { "match": { "destinazione": destinazione } }
                ],
                "minimum_should_match": 1
            }
        },
        "sort": [
            { "@timestamp": { "order": "desc" } }
        ]
    }
    
    storico_formattato = []
    try:
        risultato = es_client.search(index=NOME_INDICE_ES, body=query_storico)
        for hit in risultato["hits"]["hits"]:
            fonte = hit["_source"]
            storico_formattato.append(
                f"- Volo {fonte.get('numero_volo')} per {fonte.get('destinazione')} (Stato: {fonte.get('stato')})"
            )
    except Exception:
        pass
        
    return "\n".join(storico_formattato) if storico_formattato else "Nessun dato storico."


def analizza_condizione_volo_con_llm(numero_volo, stato_attuale, destinazione, storico_testo):
    """Invia il prompt a Ollama e classifica lo stato sintetico in una delle 4 categorie."""
    prompt = f"""
    Analizza questo volo e scegli UN UNICO VALORE tra questi 4 per descriverne la condizione principale:
    1. "orario" (se il volo è perfettamente puntuale e senza problemi storici)
    2. "in ritardo" (se lo stato attuale mostra un ritardo)
    3. "voli precedenti in ritardo" (se lo storico mostra che questo numero di volo fa spesso tardi)
    4. "stesse tratte con ritardo" (se la rotta per {destinazione} ha problemi frequenti)

    Dati volo:
    - Volo: {numero_volo}
    - Stato attuale: {stato_attuale}
    
    Storico recente:
    {storico_testo}

    Rispondi scrivendo ESATTAMENTE E SOLO una di queste 4 etichette, senza aggiungere altro testo:
    """

    payload = {
        "model": NOME_MODELLO_LLM,
        "prompt": prompt,
        "stream": False,
        "options": {
            "num_predict": 15,
            "temperature": 0.1
        }
    }

    try:
        risposta = requests.post(OLLAMA_URL, json=payload, timeout=600)
        if risposta.status_code == 200:
            testo_risposta = risposta.json().get("response", "").strip().lower()
            print(f"🤖 Risposta LLM: {testo_risposta}")
            
            if "in ritardo" in testo_risposta:
                return "in ritardo"
            elif "precedenti" in testo_risposta:
                return "voli precedenti in ritardo"
            elif "tratte" in testo_risposta:
                return "stesse tratte con ritardo"
            else:
                return "orario"
    except Exception as e:
        print(f"⚠️ Errore chiamata LLM: {e}")

    return "orario"


def elabora_singolo_volo(raw_json_volo):
    """Gestisce il flusso completo: parsing, recupero storico, LLM, timestamp UTC e salvataggio univoco su ES."""
    dati_volo = json.loads(raw_json_volo.decode('utf-8'))
    
    numero_volo = dati_volo.get('numero_volo', 'N/D')
    compagnia = dati_volo.get('compagnia', 'Altro')
    destinazione = dati_volo.get('destinazione', 'Non specificata')
    stato_attuale = dati_volo.get('stato', 'N/D')
    
    print(f"✈️ Analisi sintetica per Volo: {numero_volo} ({compagnia} -> {destinazione})")

    # 1. Recupero storico
    storico_testo = recupera_storico_volo(numero_volo, destinazione)
    
    # 2. Classificazione LLM
    stato_sintetico = analizza_condizione_volo_con_llm(numero_volo, stato_attuale, destinazione, storico_testo)
    dati_volo["stato_sintetico"] = stato_sintetico

    # 3. Formattazione timestamp UTC standard Zulu per Grafana (risolve l'errore del ricevimento)
    ora_attuale_utc = datetime.now(timezone.utc)
    dati_volo["@timestamp"] = ora_attuale_utc.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'

    # 4. Generazione ID univoco per evitare duplicazioni del medesimo volo nello stesso giorno
    data_oggi = ora_attuale_utc.strftime('%Y-%m-%d')
    doc_id = hashlib.md5(f"{numero_volo}_{data_oggi}".encode('utf-8')).hexdigest()

    # Indicizzazione id-based su Elasticsearch
    es_client.index(index=NOME_INDICE_ES, id=doc_id, document=dati_volo)
    print(f"✅ Volo {numero_volo} salvato con ID [{doc_id}] e stato: [{stato_sintetico}]\n")


def avvia_consumatore():
    """Loop di ascolto continuo sulla coda Redis."""
    print("Consumatore con metrica sintetica unica avviato...")
    while True:
        try:
            risultato_redis = connessione_redis.brpop(NOME_CODA_REDIS, timeout=5)
            if risultato_redis:
                _, raw_data = risultato_redis
                elabora_singolo_volo(raw_data)
        except redis.exceptions.TimeoutError:
            continue
        except Exception as e:
            print(f"⚠️ Errore imprevisto nel consumatore: {e}")
            time.sleep(2)


if __name__ == "__main__":
    avvia_consumatore()
