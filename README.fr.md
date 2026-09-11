<div align="center">

<img src="docs/screenshots/logo.png" width="110" alt="Logo DocumentAI"/>

# DocumentAI

**Intelligence documentaire locale – analysez des PDF, détectez et remplissez des formulaires, annotez. Entièrement hors ligne.**

Langues / Languages / Языки / 语言：
[Deutsch](README.md) | [English](README.en.md) | [Русский](README.ru.md) | **Français** | [中文](README.zh-CN.md)

![Version](https://img.shields.io/badge/Version-1.9.1-1473e6)
![Plateforme](https://img.shields.io/badge/Plateforme-Windows%2010%2F11-0078d4)
![Python](https://img.shields.io/badge/Python-3.12-3776ab)
![Hors ligne](https://img.shields.io/badge/100%25-hors%20ligne-2e7d32)
![Licence](https://img.shields.io/badge/Licence-MIT-yellow)

</div>

---

## Qu'est-ce que DocumentAI ?

DocumentAI est une application de bureau pour les documents PDF : elle
**analyse** les documents, **détecte automatiquement les champs de
formulaire**, **remplit les formulaires**, fournit **plus de 40 outils**
pour l'annotation et l'édition, **compare** des versions, **exporte**
vers les formats Office et gère les données de profil dans un **coffre
chiffré localement** – le tout sans cloud, sans compte et sans
télémétrie.

La boîte à outils reprend l'étendue fonctionnelle d'**Adobe Acrobat
Reader DC (Professional)** – reconstruite entièrement en local et hors
ligne, sans abonnement ni clé de licence.

## Fonctionnalités

### Détection des champs de formulaire
- **Modèle de paire de lignes** : légende en haut, ligne de saisie en
  dessous – le texte saisi se place **exactement sur la ligne**, comme
  à la main
- Grilles et tableaux : les cellules vides deviennent des champs ; les
  en-têtes de colonnes (par ex. les jours de la semaine) deviennent des
  cases à cocher avec des légendes explicites
- Détection du type : date, téléphone, e-mail, code postal, IBAN,
  signature, nombre, texte
- Cases à cocher détectées via les cases dessinées et les glyphes
- Les champs détectés peuvent au besoin être **déplacés à la souris**

### Outils (45)
Sélection, panoramique, insertion de champ de texte, croix/coche/point,
encercler, surligner, souligner, barrer, pense-bête, joindre un fichier,
dessin à main levée, ligne, flèche, cercle, rectangle, polygone, lignes
reliées, bulle de commentaire, légende de texte, mesure d'objets,
insertion de texte, insertion d'image, lien, filigrane, en-tête et pied
de page, numérotation Bates, couleur d'arrière-plan, masquage
(caviardage), enregistrement protégé, signature, copie certifiée,
gestion des pages (supprimer, pivoter, déplacer, fusionner),
conversion (Word, Excel, PowerPoint, texte, RTF), impression, tampon,
détection des champs, supprimer un champ, déplacer un champ, cadre de
délimitation – chaque outil avec **son propre icône** et une explication
dans la barre d'état.

### OCR
Les scans sont lus avec **Tesseract** (deu+eng). Le prétraitement
(niveaux de gris, mise à l'échelle ×2, contraste automatique) améliore
la reconnaissance des petites légendes ; l'analyse de la structure du
scan trouve les lignes de champs et les cases même sans couche texte.

### Données et confidentialité
- **Remplissage automatique** à partir des données de profil (membres
  de la famille) avec indicateur de confiance et validation
- **Coffre-fort de données** : chiffré localement (AES-256-GCM), mot de
  passe maître stocké en option dans le trousseau Windows
- **Gestion des versions** : « Enregistrer une nouvelle version »,
  annuler/rétablir, comparaison de versions (diff de texte, diff de
  champs, comparaison visuelle sous forme d'image)
- **Export** : Word (.docx), Excel (.xlsx), PowerPoint (.pptx), texte, RTF
- **Totalement local** : pas de cloud, aucune connexion réseau
  nécessaire, aucun contenu de document ne quitte votre ordinateur

### Interface
- Mise en page façon Acrobat : barre d'outils, miniatures, navigation,
  panneau de propriétés
- **Thème clair et sombre** (bascule ; le choix est mémorisé)
- Défilement à la molette, zoom, édition en place (clic dans le champ,
  Échap pour terminer)

![DocumentAI thème clair](docs/screenshots/app-hell.png)
*Détection des champs : le texte saisi se trouve sur la ligne de saisie.*

![DocumentAI thème sombre](docs/screenshots/app-dunkel.png)
*Thème sombre.*

![Outils](docs/screenshots/werkzeuge.png)
*Boîte à outils avec icônes.*

## Installation (Windows)

1. Téléchargez l'archive `DocumentAI-Installer_…_v18_1.9.1.zip` depuis
   la [page des versions](../../releases)
2. Extrayez-la (clic droit → « Extraire tout »)
3. Double-cliquez sur `DocumentAI-installieren.bat`

C'est tout. L'installation embarque son propre environnement Python et
toutes les bibliothèques – **sans droits administrateur, sans connexion
internet**. Les anciennes installations et raccourcis sont nettoyés
automatiquement (les données utilisateur sont conservées).

## Installation à partir des sources

Prérequis : Python 3.10+ (testé : 3.12) ; Tesseract en option pour l'OCR.

```bash
pip install -r requirements.txt
python DocumentAI.py            # interface graphique
python DocumentAI.py --cli …    # mode ligne de commande
python DocumentAI.py --selbsttest
```

Pour l'OCR, installez en plus le binaire Tesseract (Windows : la build
UB-Mannheim ; Debian/Ubuntu : `tesseract-ocr tesseract-ocr-deu`). Sans
Tesseract, tout le reste fonctionne normalement – l'OCR se dégrade
proprement avec un message clair.

## Architecture

| Module | Rôle |
|---|---|
| `documentai/engines/field_detector.py` | Détection visuelle des champs (paires de lignes, grilles, bandes, intervalles, cases) |
| `documentai/engines/semantic.py` | Détection des types et des noms canoniques (composés allemands) |
| `documentai/engines/ocr.py` | Intégration Tesseract avec prétraitement |
| `documentai/engines/annotate.py` | Annotations (surlignage, dessin, tampons, masquage …) |
| `documentai/engines/exporter.py` | Export/import (docx, xlsx, pptx, txt, rtf) |
| `documentai/engines/compare.py` | Comparaison de texte, de champs et visuelle |
| `documentai/engines/signatures.py` | Analyse des signatures, signature (pyhanko) |
| `documentai/services/` | Service d'analyse, profils, coffre-fort, recherche d'outils |
| `documentai/gui/` | Interface tkinter, thèmes (clair/sombre), panneaux |
| `documentai/bilder/symbole.py` | Icônes d'outils dessinées localement |
| `tests/` | 249 tests (détection de champs, IHM, pipeline, export, coffre-fort …) |

## Tests

```bash
python -m pytest tests/ -q
```

- **249 tests sur l'hôte** (unitaires + IHM sous Xvfb)
- **Laboratoire Windows** : la suite complète sous Wine
- **Vérification d'installation fraîche** : installateur → installation
  → test de fumée → test IHM, entièrement automatisé

## Construire l'installateur soi-même

L'installateur Windows est construit sous Linux à l'aide de Wine :

```bash
bash winenv/rebuild-windows-lab.sh   # monter le laboratoire Wine
bash winenv/build-installer-v5.sh    # construire le ZIP d'installation
bash winenv/verify-windows.sh        # vérifier l'installation
```

## Documentation

- [CHANGELOG](CHANGELOG.md) – toutes les versions
- [Rapport de tests](docs/TESTBERICHT.md) – historique complet de vérification (en allemand)
- [Guide de l'installateur](docs/LIESMICH.txt) – instructions d'installation jointes (en allemand)

## Sécurité et confidentialité

Voir [SECURITY.md](SECURITY.md). En bref : tout le traitement est local ;
le coffre-fort de données est chiffré en AES-256-GCM ; « Enregistrement
protégé » crée des PDF protégés par mot de passe (AES-256) ; le
masquage supprime le contenu définitivement.

## Contribuer

Voir [CONTRIBUTING.md](CONTRIBUTING.md).

## Licence

[MIT](LICENSE) – Copyright © 2026 DocumentAI.

---

<div align="center">

**DocumentAI – vos documents restent vos documents.**

</div>
