# Sorties ciné France — addon Stremio

Catalogue Stremio **« Dernières sorties en France »** : les films sortis en salles en France
sur les 3 derniers mois (sans les ressorties), triés par nombre de séances Allociné.
Addon **statique** (fichiers JSON) régénéré chaque semaine par GitHub Actions et publié sur
GitHub Pages. Usage personnel. La spécification complète est dans [SPEC.md](SPEC.md).

## Installation dans Stremio

Dans Stremio : *Addons* → champ de recherche / « Installer depuis une URL » →

```
https://adriendl.github.io/AlloSorties/manifest.json
```

Le catalogue apparaît sur l'accueil (films). Les fiches détaillées viennent de Cinemeta,
grâce aux ID IMDb (`tt…`).

## Fonctionnement

```
agenda Allociné (14 mercredis) → parsing → filtre des ressorties → TMDB (+ Wikidata)
  → data/state.json (pic de séances) → tri → dist/ (manifest + catalogue paginé)
```

| Étape | Module | Détail |
|---|---|---|
| Semaines | `weeks.py` | mercredis W tels que aujourd'hui − 91 j ≤ W ≤ aujourd'hui (Europe/Paris) |
| Téléchargement | `fetch.py` | 1 requête toutes les 2 à 3 s, 3 essais sur 5xx/timeout, arrêt immédiat sur 403/429, cache `.cache/` |
| Parsing | `parse.py`, `dates.py` | cartes `div.card.entity-card` ; liens obfusqués (base64 dans la classe CSS) décodés ; année de production lue dans le JSON `jsEntities` de la page |
| Ressorties | `filters.py` | sortie < mercredi de la page − 7 j → ressortie exclue |
| Rattachement | `tmdb.py`, `wikidata.py` | voir ci-dessous |
| Historique | `state.py` | `first_seen`, `last_seen`, `last_seances`, `peak_seances`, cache TMDB |
| Tri | `ranking.py` | `peak_seances` ↓, puis date de sortie ↓, puis titre |
| Sortie | `stremio.py` | `manifest.json`, `catalog/movie/sorties-fr.json`, `…/skip=100.json`… (pages de 100) |

### Rattachement TMDB → IMDb

1. `data/overrides.json` (`imdb_id`) ;
2. cache de `data/state.json` (rattachement réussi : jamais recalculé ; échec : retenté après 7 jours) ;
3. recherche TMDB : titre original avec puis sans année, puis titre français, puis les titres
   raccourcis avant « : », « - » (ex. *La Bataille de Gaulle - Partie 2 : …*) ;
4. score = similarité du titre normalisé (accents, casse, ponctuation, article initial)
   − malus d'année (0 si l'écart est de 0 ou 1 an avec la sortie FR **ou** l'année de production,
   0,1 si 2 ans, 0,3 au-delà) ± réalisateur (+0,1 s'il concorde, −0,2 s'il diffère),
   vérifié sur les 3 meilleurs candidats ; un titre raccourci a un malus de 0,2
   (il n'est donc accepté que si le réalisateur concorde) ;
5. accepté si score ≥ **0,85** ; l'`imdb_id` vient de `/movie/{id}?append_to_response=external_ids,credits` ;
6. **repli Wikidata** (écart assumé par rapport à SPEC.md) : pour les films non rattachés,
   une requête SPARQL relie l'ID Allociné (propriété P1265) à l'ID IMDb (P345). C'est une
   correspondance exacte, utile surtout quand TMDB connaît le film mais pas son ID IMDb ;
7. sinon, le film est exclu du catalogue et listé dans le rapport, à corriger via `overrides.json`.

**Calibrage du seuil** (données réelles du 23/09/2026, 208 nouveautés) : 155 rattachements
TMDB + 8 via Wikidata = **163 films**. Tous les rattachements acceptés ont été contrôlés à la
main : aucun faux positif. Les écarts d'année concernent des films de festival (2024-2025) ou
des films anciens sortis pour la première fois en France en 2026 (*Arrebato*, 1980). Les 45 échecs
restants sont surtout des films très confidentiels (0 à 3 séances) : titres non latins sur
TMDB, documentaires ou événements absents de TMDB, films sans ID IMDb.

### Vérification du caractère dynamique des séances (§6.4)

Relevés de la page `sem-2026-07-15` :

| Relevé | L'Odyssée | The Last Viking |
|---|---|---|
| SPEC.md (23/09/2026, plus tôt) | 592 | 50 |
| fixture, 23/09/2026 16 h 25 | 537 | 43 |
| 23/09/2026 16 h 35 et 17 h 01 | 537 | 43 |

Conclusion : le compteur « Séances (N) » reflète la **programmation courante**, pas la semaine
de sortie. Il varie d'un relevé à l'autre (592 puis 537), mais reste stable à l'échelle de
l'heure. L'Odyssée a encore 537 séances dix semaines après sa sortie, et les films qui ne sont plus
programmés n'ont plus de bloc « Séances ». D'où l'historisation de `peak_seances`. Le premier
lancement (amorçage) ne voit que le compteur courant : les films sortis il y a 3 mois
sont sous-évalués jusqu'à ce que l'historique se constitue. L'écart `last_seances` / `peak_seances`
dans `data/state.json` permettra de suivre l'évolution d'une semaine à l'autre.

## Lancement local

Prérequis : [uv](https://docs.astral.sh/uv/) (Python 3.12 est installé automatiquement).

```bash
uv sync
uv run pytest
```

Le jeton TMDB (clé API v3 ou jeton de lecture v4) est lu dans la variable `TMDB_API_KEY`,
ou dans un fichier `.env` local (exclu de git) :

```bash
echo 'TMDB_API_KEY=…' > .env
```

```bash
uv run python -m sorties_fr.main            # --refresh-all pour retélécharger toutes les semaines
```

Sorties : `dist/` (addon + `report.json`) et `data/state.json` mis à jour.
Codes de sortie : `0` succès, `1` garde-fou déclenché (rien n'est publié), `2` Allociné
inaccessible ou bloquant (403/429), `3` jeton TMDB absent ou refusé.

### Tester l'addon en local

```bash
uv run python -m sorties_fr.serve           # sert dist/ sur http://127.0.0.1:8000 avec CORS
```

Puis, dans **Stremio Desktop** : installer `http://127.0.0.1:8000/manifest.json`.
Ce serveur remplace `python -m http.server`, qui n'envoie pas l'en-tête CORS
(`Access-Control-Allow-Origin: *`, que GitHub Pages envoie).
Stremio Web (web.stremio.com) ne peut pas lire un addon local : le navigateur bloque l'accès
d'un site public à `127.0.0.1` (protection « Local Network Access »). Il faut donc passer par
GitHub Pages, ou par Stremio Desktop.

## Corrections manuelles : `data/overrides.json`

```json
{
  "1000028176": { "imdb_id": "tt6019206" },
  "305835": { "exclude": true, "reason": "doublon" }
}
```

La clé est l'identifiant Allociné (`cfilm`), visible dans l'URL de la fiche et dans le rapport.
Les films à corriger sont listés, du plus programmé au moins programmé, dans les logs et dans
`dist/report.json` (`failures`, avec la raison et le meilleur candidat TMDB).

## Rapport et garde-fous

`dist/report.json` (publié, mais non référencé par le manifest) : semaines, requêtes, films parsés,
ressorties exclues, exclusions manuelles, dates inconnues, rattachements réussis/échoués
(dont Wikidata), taille du catalogue et des pages.

Le job échoue sans rien déployer si une page agenda ne contient aucun film, si le catalogue
compte moins de 20 films, ou s'il a baissé de plus de 50 % par rapport à l'exécution précédente.

## Déploiement (GitHub Actions + Pages)

Workflow `.github/workflows/build.yml` : mercredi et jeudi à 06 h 17 UTC, plus
déclenchement manuel. Enchaînement : tests → pipeline `--refresh-all` → commit de
`data/state.json` → publication de `dist/` sur Pages.

Mise en place, une seule fois :
1. dépôt **public** (GitHub Pages gratuit) ; l'URL n'est référencée nulle part, mais elle est accessible à qui la connaît ;
2. *Settings → Pages → Source : GitHub Actions* ;
3. *Settings → Secrets and variables → Actions* : secret `TMDB_API_KEY` ;
4. *Actions → Build & deploy → Run workflow*.

Le manifest a sa propre version (`MANIFEST_VERSION` dans `config.py`) : l'incrémenter à
chaque modification du manifest, pas à chaque mise à jour du catalogue.
