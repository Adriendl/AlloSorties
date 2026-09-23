# SPEC — Addon Stremio « Dernières sorties en France »

> Document de référence destiné à un agent de code. Il décrit le besoin, les décisions déjà prises, l'architecture, les règles métier et les critères d'acceptation. En cas d'ambiguïté, privilégier la simplicité et signaler le point dans le rapport de fin de tâche plutôt que d'inventer une règle.

---

## 1. Objectif

Ajouter dans Stremio un catalogue de films intitulé **« Dernières sorties en France »**, listant les nouveautés sorties en salles en France sur les **3 derniers mois**, **sans les ressorties**, **triées par popularité** (nombre de séances Allociné).

Usage : **personnel**. Pas de publication dans le catalogue communautaire Stremio.

## 2. Décisions actées

| Sujet | Décision |
|---|---|
| Source | Pages agenda Allociné : `https://www.allocine.fr/film/agenda/sem-AAAA-MM-JJ/` (une page par mercredi) |
| Période | 3 derniers mois glissants (≈ 13 semaines) |
| Popularité | Nombre de séances affiché sur l'agenda (« Séances (N) »), avec historisation du pic observé (voir §6.4) |
| Hébergement | Addon **statique** (fichiers JSON) publié sur **GitHub Pages** |
| Exécution | **GitHub Actions** planifiée chaque semaine |
| Langage | Python 3.12 |
| Identifiants Stremio | IMDb (`tt…`) obtenus via l'API TMDB |

## 3. Architecture

```
GitHub Actions (cron hebdo + déclenchement manuel)
  └─ pipeline Python
       1. calcule les mercredis de la période
       2. télécharge les pages agenda Allociné (poli, avec cache)
       3. parse les films de chaque page
       4. filtre les ressorties
       5. rattache chaque film à un ID IMDb via TMDB (avec cache + overrides)
       6. met à jour l'historique des séances (data/state.json, commité)
       7. trie et génère les JSON Stremio dans dist/
  └─ déploiement de dist/ sur GitHub Pages
Stremio ── GET https://<user>.github.io/<repo>/manifest.json
        └─ GET …/catalog/movie/sorties-fr.json  (+ pages skip=…)
```

Aucun serveur. Stremio lit directement des fichiers statiques ; GitHub Pages renvoie `Access-Control-Allow-Origin: *`, ce qui suffit à Stremio (à vérifier au jalon 5).

## 4. Stack

- Python 3.12, gestion des dépendances avec `uv` (ou `pip` + `requirements.txt` si plus simple).
- `httpx` (client HTTP, retries), `selectolax` ou `beautifulsoup4` (parsing), `pydantic` (modèles), `rapidfuzz` (similarité de titres), `pytest`.
- Pas de navigateur headless : le HTML de l'agenda est rendu côté serveur. Si ce n'est pas le cas en pratique, le signaler avant d'introduire Playwright.
- Secret GitHub : `TMDB_API_KEY` (clé API v3 ou jeton v4, lecture seule).

## 5. Structure du dépôt

```
.
├── SPEC.md
├── README.md                  # installation, URL d'install Stremio, lancement local
├── pyproject.toml
├── src/sorties_fr/
│   ├── __init__.py
│   ├── config.py              # constantes (période, délais, user-agent, id catalogue…)
│   ├── weeks.py               # calcul des mercredis
│   ├── fetch.py               # téléchargement poli + cache disque
│   ├── parse.py               # HTML agenda -> list[AgendaFilm]
│   ├── dates.py               # parsing des dates françaises
│   ├── filters.py             # détection des ressorties
│   ├── tmdb.py                # recherche + external_ids + scoring
│   ├── state.py               # lecture/écriture data/state.json
│   ├── ranking.py             # tri
│   ├── stremio.py             # génération manifest + catalogue
│   └── main.py                # orchestration, rapport final, codes de sortie
├── data/
│   ├── state.json             # historique (commité par la CI)
│   └── overrides.json         # correspondances manuelles cfilm -> imdb_id / exclusions
├── tests/
│   ├── fixtures/agenda_2026-07-15.html
│   └── test_*.py
└── .github/workflows/build.yml
```

## 6. Règles métier

### 6.1 Semaines à récupérer

- Les URL d'agenda sont indexées par un **mercredi** : `sem-2026-07-15`.
- Période : tous les mercredis `W` tels que `aujourd'hui − 91 jours ≤ W ≤ aujourd'hui` (fuseau Europe/Paris).
- Ne jamais récupérer de semaine future.

### 6.2 Extraction (par film, depuis la page agenda)

| Champ | Exemple observé | Obligatoire |
|---|---|---|
| `cfilm_id` | `1000013045` (depuis `fichefilm_gen_cfilm=1000013045.html`) | oui, clé primaire |
| `title_fr` | `L'Odyssée` | oui |
| `title_original` | `The Odyssey` (ligne « Titre original ») ; absent si identique | non → défaut `title_fr` |
| `release_date` | `15 juillet 2026` | non (voir 6.3) |
| `genres` | `Action, Fantastique` | non |
| `directors` | `Christopher Nolan` (ligne « De ») | non |
| `cast` | `Matt Damon, Tom Holland, Anne Hathaway` | non |
| `press_rating` / `user_rating` | `4,1` / `4,3` (virgule décimale) | non |
| `synopsis` | texte | non |
| `seances` | `592` (depuis « Séances (592) ») ; absent → `0` | non |
| `poster_url` | URL `acsta.net` ; parfois vide | non |
| `agenda_week` | date du mercredi de la page | oui |

Consignes :
- Les sélecteurs CSS ne sont pas fournis : les déterminer à partir du HTML réel, puis **figer une page en fixture** (`tests/fixtures/`) pour les tests.
- Les dates sont en français (`15 juillet 2026`, `1 juillet 2026`, parfois `1er`) : implémenter un parseur dédié avec table des mois, sans dépendre de la locale système.
- Un film sans `cfilm_id` est ignoré et journalisé.

### 6.3 Filtrage des ressorties

Une page agenda mélange nouveautés et ressorties (ex. semaine du 15/07/2026 : rétrospective Jacques Tati, Kim Jee-woon, Hitchcock). La date affichée est la **date de sortie originale**, ce qui permet la règle suivante :

- `release_date ≥ agenda_week − 7 jours` → **nouveauté**, conservée.
- `release_date < agenda_week − 7 jours` → **ressortie**, exclue.
- `release_date` absente ou illisible → conservée, marquée `date_unknown` dans le rapport.
- Exclusion manuelle possible via `overrides.json` (`"exclude": true`).

### 6.4 Popularité et historisation

Le compteur « Séances (N) » est très probablement le nombre de séances **au moment du scraping**, pas celui de la semaine de sortie : un film sorti il y a trois mois apparaît donc avec peu ou pas de séances, même s'il a été un succès. Pour corriger ce biais sans changer de source :

- `data/state.json` conserve pour chaque `cfilm_id` : `first_seen`, `last_seen`, `last_seances`, `peak_seances` (max observé), plus le cache TMDB (§6.5).
- Chaque exécution met à jour ces valeurs ; le fichier est commité par la CI.
- **Tri du catalogue** : `peak_seances` décroissant, puis `release_date` décroissante, puis `title_fr`.
- Premier lancement (amorçage) : seul le compteur courant est disponible, accepter ce biais initial ; il se résorbe au fil des semaines.
- Vérification demandée (jalon 2) : comparer le compteur d'une même page à deux dates pour confirmer qu'il est dynamique, et consigner le résultat dans le README.

### 6.5 Rattachement TMDB → IMDb

Stremio (Cinemeta et addons de streams) a besoin d'un ID `tt…`. Procédure :

1. Si `overrides.json` fournit un `imdb_id` pour ce `cfilm_id` → l'utiliser.
2. Si `state.json` contient déjà un rattachement validé → le réutiliser (ne pas rappeler TMDB).
3. Sinon `GET /search/movie` avec `query=title_original`, `year=` année de sortie, `language=fr-FR` ; si rien, relancer sans `year`, puis avec `title_fr`.
4. Scorer les candidats : similarité de titre normalisé (accents, casse, ponctuation, articles) sur titre original et titre français, écart d'année (0 ou 1 toléré, les sorties françaises suivent souvent les festivals), et en départage le réalisateur via `/movie/{id}/credits`.
5. Accepter si score ≥ seuil (à calibrer sur la fixture, valeur de départ 0,85), puis récupérer `imdb_id` via `/movie/{id}?append_to_response=external_ids`.
6. Échec (aucun candidat, score insuffisant ou pas d'`imdb_id`) → film **exclu du catalogue** et listé dans le rapport « à corriger via overrides.json ».

Respecter le rate limit TMDB (quelques requêtes par seconde suffisent) et mettre en cache aussi les échecs (avec date) pour ne retenter qu'une fois par semaine.

Format `overrides.json` :
```json
{
  "1000013045": { "imdb_id": "tt0000000" },
  "305835": { "exclude": true, "reason": "doublon" }
}
```

## 7. Sortie Stremio (addon statique)

### 7.1 `dist/manifest.json`

```json
{
  "id": "perso.sorties-fr.allocine",
  "version": "1.0.0",
  "name": "Sorties ciné France",
  "description": "Nouveautés sorties en salles en France sur les 3 derniers mois, sans ressorties, triées par nombre de séances.",
  "resources": ["catalog"],
  "types": ["movie"],
  "idPrefixes": ["tt"],
  "catalogs": [
    { "type": "movie", "id": "sorties-fr", "name": "Dernières sorties en France" }
  ]
}
```

Incrémenter `version` à chaque changement du manifest (pas à chaque mise à jour du catalogue).

### 7.2 Catalogue et pagination

- Première page : `dist/catalog/movie/sorties-fr.json`
- Pages suivantes : `dist/catalog/movie/sorties-fr/skip=100.json`, `skip=200.json`, … (100 éléments par page).
- Format : `{ "metas": [ … ] }`.

Chaque méta :
```json
{
  "id": "tt…",
  "type": "movie",
  "name": "L'Odyssée",
  "poster": "https://image.tmdb.org/t/p/w500/…",
  "releaseInfo": "2026",
  "genres": ["Action", "Fantastique"],
  "description": "Sortie le 15 juillet 2026 · 592 séances · Presse 4,1 · Spectateurs 4,3\n\n<synopsis>"
}
```

- Poster : privilégier TMDB (`poster_path`), repli sur l'URL Allociné si absent.
- Les fiches détaillées sont fournies par Cinemeta grâce à l'ID IMDb : ne pas implémenter la ressource `meta`.

## 8. Politesse et robustesse du scraping

- User-Agent explicite et identifiable (nom du projet + URL du dépôt).
- Une requête toutes les 2 à 3 secondes, séquentielle ; 3 tentatives avec backoff exponentiel sur erreurs 5xx/timeouts ; aucune retente sur 403/429 (arrêt et rapport).
- Seules les pages agenda sont récupérées (≈ 14 requêtes par exécution) ; aucune fiche film.
- Cache disque des pages : les semaines de plus de 14 jours peuvent être relues depuis le cache, sauf pour rafraîchir les séances (paramètre `--refresh-all`, activé par défaut en CI).

**Garde-fous avant publication** (le job échoue et ne déploie rien sinon) :
- chaque page récupérée contient au moins 1 film parsé ;
- le catalogue final contient au moins 20 films ;
- baisse de plus de 50 % du nombre de films par rapport à l'exécution précédente → échec (probable changement de structure HTML).

Rapport en fin d'exécution (log + `dist/report.json`, non référencé dans le manifest) : nombre de semaines, films parsés, ressorties exclues, dates inconnues, rattachements réussis/échoués avec la liste des échecs.

## 9. GitHub Actions (`.github/workflows/build.yml`)

- Déclencheurs : `schedule` le mercredi et le jeudi matin (UTC), plus `workflow_dispatch`.
- Étapes : checkout → Python + dépendances → tests → pipeline → commit de `data/state.json` si modifié → `actions/upload-pages-artifact` (dossier `dist/`) → `actions/deploy-pages`.
- Permissions : `contents: write`, `pages: write`, `id-token: write`.
- Note : GitHub Pages gratuit impose un dépôt public (compte gratuit). L'URL n'est pas référencée publiquement, mais elle est accessible à qui la connaît.

URL d'installation dans Stremio : `https://<user>.github.io/<repo>/manifest.json`.

## 10. Tests et critères d'acceptation

Tests unitaires sur la fixture de la semaine du 15/07/2026 :

- `L'Odyssée` : parsé, `cfilm_id = 1000013045`, `release_date = 2026-07-15`, `seances = 592`, `title_original = "The Odyssey"`, **conservé**.
- `The Last Viking` : conservé, `seances = 50`.
- `Playtime` (1967), `Mon oncle` (1958), `Le Crime était presque parfait` (1955), `2 soeurs` (2004), `Ça tourne à Séoul ! Cobweb` (2023) : **exclus** comme ressorties.
- `Ça tourne à Séoul ! Cobweb` et `Foul King` n'ont pas de bloc séances → `seances = 0` sans erreur.
- Un film sans titre original prend `title_fr` par défaut (ex. `Comète`).
- Parseur de dates : `1 juillet 2026`, `1er juillet 2026`, `16 décembre 1967`, chaîne vide.
- Calcul des semaines : pour le mercredi 23/09/2026, la première semaine est celle du 24/06/2026 et la dernière celle du 23/09/2026.
- Tri : à `peak_seances` égal, la sortie la plus récente passe devant.
- Génération Stremio : manifest valide, pagination correcte avec 250 films fictifs (pages de 100, 100, 50).

Note : les valeurs de séances de la fixture sont celles relevées le 23/09/2026 ; si la fixture est capturée plus tard, adapter les valeurs attendues à la fixture réelle.

Tests TMDB avec réponses mockées (aucun appel réseau en CI de test).

Critère final : après déploiement, l'addon s'installe dans Stremio depuis l'URL, le catalogue « Dernières sorties en France » s'affiche sur l'accueil, les fiches s'ouvrent correctement.

## 11. Jalons

1. **Parsing** : récupération d'une page, fixture, parseur, dates, filtre ressorties, tests §10.
2. **Période et état** : itération sur 13 semaines, cache, `state.json`, vérification du caractère dynamique des séances.
3. **TMDB** : rattachement, scoring, overrides, rapport des échecs.
4. **Stremio** : génération `dist/`, test local (`python -m http.server` dans `dist/`, installation via `http://127.0.0.1:8000/manifest.json` dans Stremio Desktop).
5. **CI/CD** : workflow, garde-fous, déploiement Pages, vérification CORS et installation réelle.

## 12. Hors périmètre (idées futures)

- Catalogues filtrés par genre (`extra: genre`).
- Score composite avec box-office France.
- Ressource `meta` propre pour les films sans ID IMDb.
- Addon serveur avec paramètres utilisateur (période configurable).
