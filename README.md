# Ave del Día

Feed RSS y mini-sitio estático que publican una especie de ave nueva cada día,
con sesgo hacia la península ibérica y Europa pero sin restringirse a ninguna
región. Datos en directo de [eBird](https://ebird.org) y
[Cornell Lab of Ornithology](https://www.birds.cornell.edu/), foto del día desde
la [Macaulay Library](https://www.macaulaylibrary.org/), descripción de campo
en castellano traída directamente de Merlin/eBird.

Cero contenido generado por IA, cero coste de hosting, cero tracking.

## Lo que ves al desplegarlo

GitHub Pages sirve tres rutas estáticas desde la raíz del repo:

| Ruta | Qué es |
|---|---|
| `/` (`index.html`) | El ave del día como hero, las 12 últimas como grid de cards |
| `/archive.html` | Todas las aves publicadas en orden cronológico inverso, con anchors permanentes (`#bird-{code}-{fecha}`) |
| `/feed.xml` | Feed RSS 2.0 suscribible, con `content:encoded` HTML rico |

Todo es HTML estático, sin JavaScript ni build step.

## Cómo funciona

```
GitHub Actions (cron diario 07:00 UTC)
  │
  ├─ 1. Pool ponderado por fecha (35% Madrid, 27% España,
  │     23% un país europeo aleatorio, 15% taxonomía global)
  ├─ 2. Selección de especie con sesgo inverso a abundancia,
  │     deduplicada contra las últimas 50 publicaciones
  ├─ 3. Foto y fotógrafo desde Macaulay Library Search API
  │     (con fallback a og:image de la página de eBird)
  ├─ 4. Descripción Merlin en castellano + intro Birds of the World
  ├─ 5. Reescritura de feed.xml + index.html + archive.html
  └─ 6. git commit + git push → GitHub Pages re-publica
```

La selección es **determinista por fecha**: dos ejecuciones del mismo día
seleccionan exactamente la misma ave. La idempotencia se controla con
`history.json`: si ya hay entrada para hoy, el script termina sin tocar nada.

## Stack

- Python 3.12+, gestionado con [`uv`](https://github.com/astral-sh/uv)
- Dependencias mínimas: `requests` y `beautifulsoup4`
- Sin base de datos. Estado en tres ficheros del repo: `feed.xml`,
  `history.json`, `cache/`

## Instalación local

```bash
git clone https://github.com/backmind/Bird-of-the-day.git
cd Bird-of-the-day
uv sync
```

`uv sync` crea el venv en `.venv/` e instala las dependencias del `pyproject.toml`.

## Configuración

### Variables de entorno

| Variable | Obligatoria | Origen |
|---|---|---|
| `EBIRD_API_KEY` | sí | Pídela gratis en <https://ebird.org/api/keygen> |

Para uso local copia `.env.example` a `.env` y rellena la clave:

```bash
cp .env.example .env
# editar .env y poner tu key
```

`.env` está en `.gitignore` y `generate.py` la carga automáticamente al
arrancar (no hace falta `python-dotenv`).

En GitHub Actions la clave se inyecta desde `Settings → Secrets and
variables → Actions → New repository secret` con el mismo nombre.

### Pesos de pools y otros parámetros

`data/config.json` controla las regiones, sus pesos, los límites del feed
y la URL pública del proyecto:

```json
{
  "pools": [
    {"id": "madrid", "region": "ES-MD", "weight": 0.35, "type": "regional"},
    {"id": "spain",  "region": "ES",    "weight": 0.27, "type": "regional"},
    {"id": "europe", "weight": 0.23, "type": "europe_random",
     "countries": ["PT", "FR", "IT", "DE", "GB", "GR", "SE", "NO", "PL"]},
    {"id": "global", "weight": 0.15, "type": "global_taxonomy"}
  ],
  "max_history": 50,
  "max_feed_entries": 60,
  "ebird_locale": "es",
  "back_days": 14,
  "feed_title": "Ave del Día",
  "feed_description": "Cada día, una especie de ave. Con sesgo ibérico, pero sin fronteras.",
  "feed_link": "https://backmind.github.io/Bird-of-the-day/"
}
```

Cambia `feed_link` por la URL real de tu fork antes de publicar.

## Ejecución

### Local

```bash
uv run python -m scripts.generate
```

Esto:
1. Carga `.env` si existe.
2. Verifica si ya hay una entrada para hoy en `history.json` y, si la hay, sale.
3. Selecciona la especie del día.
4. Resuelve imagen y contenido (consulta la red, escribe a `cache/`).
5. Reescribe `feed.xml`, `index.html` y `archive.html`.
6. Actualiza `history.json`.

Para forzar una regeneración del día, vacía `history.json`:

```bash
echo '{"entries": []}' > history.json
uv run python -m scripts.generate
```

### Vía GitHub Actions

El workflow `.github/workflows/ave-del-dia.yml` se ejecuta:

- Automáticamente cada día a las **07:00 UTC** (09:00 CEST en Madrid).
- Manualmente desde la pestaña **Actions → Ave del Día → Run workflow**.

El workflow hace `git add` de `feed.xml`, `history.json`, `index.html`,
`archive.html` y `cache/`, commitea con un mensaje del estilo
`🐦 Ave del día: 2026-04-11` y empuja a la rama por defecto.

## Despliegue (GitHub Pages)

1. **Settings → Pages → Build and deployment**
2. *Source*: `Deploy from a branch`
3. *Branch*: la rama donde corre el workflow (normalmente `main`),
   carpeta `/ (root)`
4. Guarda y espera 1–2 minutos a que GitHub publique

Tras el primer deploy tendrás:

- Feed RSS: `https://<usuario>.github.io/<repo>/feed.xml`
- Sitio: `https://<usuario>.github.io/<repo>/`
- Archivo: `https://<usuario>.github.io/<repo>/archive.html`

Pon esa misma URL en `data/config.json` → `feed_link`.

## Estructura del repo

```
Bird-of-the-day/
├── .github/workflows/ave-del-dia.yml   # cron diario + commit
├── scripts/
│   ├── generate.py        # orquestador (entry point)
│   ├── ebird_client.py    # API eBird + selección + caché de taxonomía
│   ├── image_fetcher.py   # Macaulay Library API + fallback og:image
│   ├── content_scraper.py # og:description de eBird + intro de BoW
│   ├── feed_builder.py    # generación del RSS 2.0
│   └── site_builder.py    # generación de index.html + archive.html
├── data/
│   └── config.json        # pesos de pools, límites, metadata del feed
├── cache/                 # contenido y taxonomía cacheados (commiteados)
├── feed.xml               # generado: RSS 2.0
├── index.html             # generado: hero + grid
├── archive.html           # generado: archivo completo
├── history.json           # generado: histórico de publicaciones
├── pyproject.toml         # dependencias y metadata uv
├── uv.lock                # lock file
├── .env.example           # plantilla de variables de entorno
├── LICENSE                # MIT
└── README.md
```

## Atribuciones y consideraciones legales

- **eBird API**: uso no comercial permitido bajo
  [eBird API Terms of Use](https://ebird.org/api/keygen). El proyecto realiza
  como mucho una llamada diaria.
- **Macaulay Library**: las fotografías son © de sus autores. Este proyecto
  hace *hot-linking* al CDN público de Cornell para visualización no comercial
  con atribución visible al fotógrafo, que es el modelo que la propia Cornell
  ofrece a través de su sistema de embed.
- **Textos de Merlin/eBird y Birds of the World**: contenido © Cornell Lab of
  Ornithology. El feed reproduce fragmentos breves con atribución clara,
  enlaces a la fuente original y sin propósito comercial.
- **Datos generados por este proyecto** (feed, sitio): MIT, libres de
  reutilización con atribución.

## Licencia

Código bajo licencia [MIT](LICENSE). El contenido de terceros (fotos, textos
de Cornell) mantiene sus respectivas licencias y atribuciones.
