import asyncio
import json
import redis
from playwright.async_api import async_playwright

# Connessione principale a Redis
connessione_redis = redis.Redis(host='localhost', port=6379, decode_responses=True)
NOME_CODA_REDIS = "coda_voli_catania"


def estrai_campi_volo(testo_riga):
    """Esegue il parsing delle righe di testo estratte dalla pagina web."""
    linee = [linea.strip() for linea in testo_riga.split('\n') if linea.strip()]
    
    destinazione = "Non specificata"
    compagnia = "Altro"
    numero_volo = "Non specificato"
    
    # Gestione dello stato più robusta
    stato = "In orario"
    if linee:
        stato_candidate = linee[0]
        if stato_candidate in ["Destinazione", "Compagnia", "Numero volo"]:
            stato = "In orario"
        else:
            stato = stato_candidate

    for i, valore in enumerate(linee):
        if valore == "Destinazione" and i + 1 < len(linee):
            destinazione = linee[i + 1]
        elif valore == "Compagnia" and i + 1 < len(linee):
            compagnia = linee[i + 1]
        elif valore == "Numero volo" and i + 1 < len(linee):
            numero_volo = linee[i + 1]

    return {
        "testo_originale": testo_riga,
        "origine": "Aeroporto di Catania",
        "destinazione": destinazione,
        "compagnia": compagnia,
        "numero_volo": numero_volo,
        "stato": stato
    }


async def scansiona_pagina_voli(pagina_web, numero_pagina):
    """Carica una singola pagina del tabellone ed estrae i blocchi di testo dei voli."""
    url_pagina = f"https://www.aeroporto.catania.it/tracking-voli/partenze?type=DEPARTURES&date=TODAY&page={numero_pagina}&timeRange="
    await pagina_web.goto(url_pagina, wait_until="networkidle")

    try:
        await pagina_web.wait_for_selector("text=Numero volo", timeout=15000)
    except Exception:
        print(f"⚠️ Timeout: Nessun volo trovato nella pagina {numero_pagina}.")
        return []

    testi_righe = await pagina_web.evaluate('''() => {
        let elementi = document.querySelectorAll('div, tr');
        let voli = [];
        for (let el of elementi) {
            let t = el.innerText;
            if (t && t.includes("Numero volo") && t.includes("Destinazione") && t.length < 400) {
                voli.push(t);
            }
        }
        return [...new Set(voli)];
    }''')

    return testi_righe


async def esegui_ciclo_scraping(browser):
    """Gestisce un intero ciclo di lettura (prime 3 pagine) e invio a Redis."""
    print("\n--- [H24] Avvio nuovo ciclo di scraping dei voli ---")
    pagina_web = await browser.new_page()

    for numero_pagina in range(1, 4):
        print(f"Sto leggendo la pagina numero {numero_pagina}...")
        testi_righe = await scansiona_pagina_voli(pagina_web, numero_pagina)
        
        if not testi_righe:
            break

        print(f"Trovate {len(testi_righe)} righe complete nella pagina {numero_pagina}.")

        for testo in testi_righe:
            dati_volo = estrai_campi_volo(testo)
            volo_json = json.dumps(dati_volo)
            connessione_redis.lpush(NOME_CODA_REDIS, volo_json)
            print(f"✅ Volo inviato -> Vettore: {dati_volo['compagnia']} | Volo: {dati_volo['numero_volo']} | Destinazione: {dati_volo['destinazione']}")

    await pagina_web.close()
    print("Ciclo completato. In attesa del prossimo controllo...")


async def avvia_monitoraggio_h24():
    """Loop infinito che esegue lo scraping ogni 5 minuti."""
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True, args=["--no-sandbox"])
        while True:
            try:
                await esegui_ciclo_scraping(browser)
            except Exception as e:
                print(f"⚠️ Errore riscontrato nel ciclo di scraping: {e}")
            
            await asyncio.sleep(300)


if __name__ == "__main__":
    print("Avvio lo scraper produttore in modalità H24...")
    asyncio.run(avvia_monitoraggio_h24())
