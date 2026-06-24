## Projet fait par Mathis Chabault et Tom Boulec

## ⚙️ Prérequis

- **Python 3.10+**
- **pip**
- Connexion Internet (pour l'API OpenF1 et Project Gutenberg)

---

## 🚀 Installation

**1. Clone le repository**
```bash
git clone https://github.com/TON_USERNAME/python-avance-projet.git
cd python-avance-projet
```

**2. Installe les dépendances**
```bash
pip install requests pillow python-docx matplotlib
```

---

## 🏎️ Partie 1 — Application Desktop F1

### Description

Application graphique développée avec **Tkinter** qui :
- Se connecte à l'**API OpenF1** pour récupérer les données de la dernière course F1 (saison 2024)
- Stocke les pilotes et leurs temps de tour dans une base **SQLite**
- Affiche un classement par temps moyen avec les **couleurs officielles des écuries**
- Génère des **graphiques interactifs** directement dans la fenêtre

### Lancement

```bash
python partie1_f1_app.py
```

### Fonctionnalités

#### Menu & Toolbar
| Bouton | Action |
|--------|--------|
| 📥 Télécharger | Récupère les données F1 depuis OpenF1 API |
| 🗑️ Effacer DB | Supprime toutes les données de la base SQLite |
| 📊 Graphique | Affiche le graphique des temps moyens par pilote |
| 🏆 Meilleurs tours | Affiche le graphique des meilleurs tours par pilote |
| 📈 Agrégation SQL | Affiche les statistiques calculées via requête SQL |

#### Menu Options
- 🎨 **Couleur de fond** — personnalise la couleur de l'interface
- 🔤 **Changer police** — modifie la famille et la taille de police

#### Détails techniques
- **API** : [OpenF1](https://openf1.org) — données F1 gratuites en temps réel
- **Session ciblée** : dernière course Race de la saison 2024 (données garanties)
- **Anti rate-limit** : pause de 2 secondes entre chaque appel de tours pilote
- **Threading** : le téléchargement tourne en arrière-plan, l'UI reste réactive
- **Status bar** : horodatage + statut de la dernière opération en bas de fenêtre

#### Base de données SQLite

```sql
-- Table des pilotes
CREATE TABLE drivers (
    driver_number INTEGER PRIMARY KEY,
    full_name     TEXT,
    team_name     TEXT,
    country_code  TEXT,
    session_key   INTEGER
);

-- Table des temps de tour
CREATE TABLE lap_times (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    driver_number INTEGER,
    lap_number    INTEGER,
    lap_duration  REAL,
    session_key   INTEGER
);
```

### Capture d'écran

> *(à compléter avec une capture de l'application en fonctionnement)*

---

## 📚 Partie 2 — Analyse Littéraire & Rapport Word

### Description

Script Python qui exécute un pipeline complet en 7 étapes :

```
[1] Téléchargement du livre  →  [2] Extraction métadonnées & chapitre I
        ↓
[3] Analyse paragraphes      →  [4] Génération graphique distribution
        ↓
[5] Traitement image         →  [6] Logo N&B + composition
        ↓
[7] Génération rapport Word
```

**Livre analysé** : *Vingt mille lieues sous les mers* — Jules Verne (1870)  
**Source** : [Project Gutenberg](https://www.gutenberg.org/ebooks/54873)

### Lancement

```bash
python partie2_rapport_word.py
```

### Fonctionnalités détaillées

#### Extraction du texte
- Téléchargement du livre au format `.txt` depuis Gutenberg
- Extraction automatique du **titre** et de l'**auteur** depuis l'en-tête
- Isolation du **premier chapitre** par détection des marqueurs `CHAPITRE PREMIER` / `CHAPITRE II`

#### Analyse des paragraphes
- Découpage en paragraphes (normalisation `\r\n` Windows)
- Comptage des mots par paragraphe (`re.findall`)
- **Arrondi à la dizaine** : 123 → 120, 127 → 120, 130 → 130
- Calcul des statistiques : min, max, moyenne, total

#### Graphique
- Distribution des longueurs de paragraphes (arrondies)
- Thème dark (fond `#1a1a2e`) avec barres rouges
- Sauvegardé en PNG 150 DPI

#### Traitement image
- Utilise `JulesVerne.jpg` si présent dans le dossier (priorité)
- Sinon tente plusieurs URLs Wikipedia avec fallback
- En dernier recours : génère une illustration océan automatiquement
- **Recadrage centré** au ratio 4:3
- **Redimensionnement** à 800×600 px

#### Logo & Composition
- Logo noir et blanc généré avec Pillow (cercles + texte)
- **Rotation de 30°** puis collage en bas à droite de l'image

#### Rapport Word
Le rapport généré contient :
- **Page de titre** : titre du livre (gras italique), image composée, auteur, auteur du rapport, date
- **Page d'analyse** : graphique de distribution, description de l'œuvre, tableau de statistiques avec alternance de couleurs

### Fichiers générés

| Fichier | Description |
|---------|-------------|
| `output_partie2/chart_paragraphes.png` | Graphique distribution paragraphes |
| `output_partie2/logo_bw.png` | Logo N&B généré |
| `output_partie2/image_finale.jpg` | Image recadrée + logo collé |
| `output_partie2/rapport_20000_lieues.docx` | Rapport Word final |

---

## 🧪 Tests unitaires

Les deux scripts embarquent leurs propres tests unitaires, exécutables sans interface graphique.

### Partie 1 — 8 tests

```bash
python partie1_f1_app.py --tests
```

| Test | Description |
|------|-------------|
| `test_format_time_zero` | `format_time(0)` → `"0:00.000"` |
| `test_format_time_normal` | `format_time(90.123)` → `"1:30.123"` |
| `test_format_time_none` | `format_time(None)` → `"—"` |
| `test_format_time_sub_minute` | Vérification du format minute |
| `test_save_and_count` | Sauvegarde pilote + comptage DB |
| `test_clear_db` | Vidage de la base |
| `test_save_laps` | Sauvegarde tours + calcul moyenne |
| `test_null_lap_ignored` | Les tours `None` sont ignorés |

### Partie 2 — 10 tests

```bash
python partie2_rapport_word.py --tests
```

| Test | Description |
|------|-------------|
| `test_count_words_basic` | Comptage mots basique |
| `test_count_words_empty` | Chaîne vide → 0 |
| `test_count_words_punctuation` | Ponctuation non comptée |
| `test_round_to_ten` | 123→120, 130→130, 9→0 |
| `test_split_paragraphs` | Découpage en paragraphes |
| `test_compute_stats` | min/max/moy corrects |
| `test_compute_stats_empty` | Liste vide → stats nulles |
| `test_extract_metadata_fallback` | Extraction titre/auteur |
| `test_distribution_counter` | Distribution correcte |
| `test_chart_creates_file` | Graphique bien sauvegardé |

---

## 🛠️ Technologies utilisées

| Librairie | Usage |
|-----------|-------|
| `tkinter` | Interface graphique desktop (Partie 1) |
| `sqlite3` | Base de données locale (Partie 1) |
| `requests` | Appels API et téléchargements HTTP |
| `matplotlib` | Génération de graphiques |
| `Pillow` | Traitement d'images (recadrage, rotation, composition) |
| `python-docx` | Génération du rapport Word |
| `threading` | Téléchargement asynchrone (Partie 1) |
| `re` | Extraction de texte par expressions régulières |
| `collections.Counter` | Distribution des longueurs de paragraphes |
| `unittest` | Tests unitaires |
