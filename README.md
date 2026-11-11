# RLCmeter

Mesure d'impédance avec un HP 4194A (GPIB) et modélisation Foster / Cauer.
Remplace le classeur Excel `RLCmeter_extractorV4.xls` (code VBA d'origine dans `docs/vba`).

## Lancer

```
..\Scripts\python.exe main.py
..\Scripts\python.exe -m pytest tests
```

## Utilisation

1. **Acquisition** (panneau de droite) : liaison `Simulation` ou `GPIB`, adresse, plage,
   nombre de points, temps d'intégration. `Tester la liaison`, puis `Mesurer` (F5).
2. Chaque mesure devient une **capture** de la librairie (`library/`, un fichier `.json`).
   Case cochée = affichée ; double-clic lent ou F2 = renommer.
3. **Ajuster un modèle** (Ctrl+M) sur la capture sélectionnée. Les réglages du modèle
   (type, plage de fréquence, ordre, capacité parallèle) relancent le fit à chaque
   changement ; la plage se règle aussi à la souris sur le graphe du haut.
4. **Exporter** : modèle en `.subckt` pour LTspice, capture en `.csv`.
5. **Utilitaires > Options** : répertoire de la librairie (ses sous-répertoires deviennent
   des dossiers de l'arborescence) et réglages par défaut d'un nouveau modèle.
6. **Utilitaires > Création de filtre** : filtre L, T ou Pi à partir de captures, de
   modèles ou de composants idéaux ; gain d'insertion, coupure, atténuation.

Le tutoriel complet est dans `docs/tutoriel.md` (menu Aide, F1).

## Organisation

| Dossier | Rôle |
|---|---|
| `instrument/hp4194a.py` | pilote VISA du 4194A et instrument simulé |
| `model/capture.py` | capture (Z complexe), grandeurs dérivées, réglages d'un modèle |
| `model/fit.py` | modèles d'inductance (Foster / Cauer) et de condensateur, fit, choix de l'ordre par AIC |
| `model/library.py` | librairie de captures sur disque |
| `model/spice.py` | export `.subckt` |
| `model/filter.py` | réponse d'un filtre en échelle (matrices chaîne) |
| `controller/` | contrôleur principal, mesure en tâche de fond, création de filtre |
| `view/` | fenêtre principale (arbre, graphes, paramètres), fenêtre de filtre |
| `ressources/theme.py` | thème clair / sombre, repris de GLviewer |
| `ressources/options_panel.py` | fenêtre d'options générée par schéma, reprise de GLviewer |
| `ressources/app_settings.py` | schéma des options |

## Choix à connaître

- La mesure est faite en **R-X** et stockée en impédance complexe ; Ls-Rs, |Z|-Theta et
  Cs-Rs sont calculés par le PC (modèle série).
- **Fin de balayage** : `Durée estimée` reprend l'attente fixe de la macro Excel ;
  `Octet d'état` interroge l'appareil et rend la main dès la fin du balayage. Ce second
  mode n'a pas été validé sur l'appareil (bit de fin de balayage à confirmer).
- Une seule branche Rp // Cp : deux branches en parallèle sont équivalentes à une seule.
