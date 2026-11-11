import json
import instaloader
import redis

# Configurazione costanti e connessione Redis
HOST_REDIS = 'localhost'
PORTA_REDIS = 6379
NOME_CODA_REDIS = "coda_instagram"

TARGET_PROFILO = "ctaairport"
MAX_POST_DA_SCARICARE = 5

connessione_redis = redis.Redis(host=HOST_REDIS, port=PORTA_REDIS, db=0, decode_responses=True)


def estrai_dati_post(post):
    """Estrae i campi di interesse da un oggetto Post di Instaloader."""
    return {
        "id": post.shortcode,
        "testo": post.caption if post.caption else "",
        "data_pubblicazione": post.date_utc.isoformat(),
        "url_immagine": post.url,
        "link_post": f"https://www.instagram.com/p/{post.shortcode}/"
    }


def esegui_scraping_instagram():
    """Scarica gli ultimi post dal profilo target e li inserisce nella coda Redis."""
    istanza_instaloader = instaloader.Instaloader(quiet=True)
    
    print(f"Scaricando gli ultimi {MAX_POST_DA_SCARICARE} post da @{TARGET_PROFILO}...")
    
    try:
        profilo = instaloader.Profile.from_username(istanza_instaloader.context, TARGET_PROFILO)
        
        for indice, post in enumerate(profilo.get_posts()):
            if indice >= MAX_POST_DA_SCARICARE:
                break
            
            dati_post = estrai_dati_post(post)
            post_json = json.dumps(dati_post)
            
            connessione_redis.lpush(NOME_CODA_REDIS, post_json)
            print(f"✅ Inviato a Redis -> Post ID: {post.shortcode}")
            
        print("Scraping completato con successo.")

    except Exception as errore:
        print(f"⚠️ Errore durante lo scraping di Instagram: {errore}")


if __name__ == "__main__":
    esegui_scraping_instagram()
