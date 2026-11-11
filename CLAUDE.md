# RLCmeter — contexte pour Claude

Application de bureau Python qui remplace le classeur Excel/VBA `RLCmeter_extractorV4.xls`
(code d'origine dans `docs/vba`) : pilotage d'un analyseur d'impédance **HP 4194A** en GPIB,
librairie de composants mesurés, modélisation, export LTspice, estimation de filtres.
Dépôt : https://github.com/florianmontaut/RLCmeter (branche `main`).

## Travailler avec l'utilisateur

- Répondre en **français**. Avis francs, formulés avec douceur.
- Ne committer / pousser que sur demande explicite (« Oui, pousse »).
- Ne pas versionner les fichiers de mesure de l'utilisateur (`library/*.json`) sans son accord.
- Proposer et discuter l'approche avant un développement important.

## Environnement

- Python 3.11, PyQt6 6.4.2, pyqtgraph 0.13.3, numpy 1.24.3, scipy 1.11.3, PyVISA 1.16.2,
  qdarktheme, pytest (`requirements.txt`).
- Sur le PC d'origine, le dossier est dans un venv (`...\dev\.venv\RLCmeter`), d'où
  `..\Scripts\python.exe main.py` et `..\Scripts\python.exe -m pytest tests`.
  Sur un autre PC, utiliser l'interpréteur de l'environnement local.
- Matériel : Keysight IO Libraries + adaptateur 82357B, adresse `GPIB0::17::INSTR`.
- L'interface s'inspire d'un autre projet de l'utilisateur, **GLviewer** (thème, icônes,
  `OptionsPannel` portés dans `ressources/`). Il n'est pas dans ce dépôt.

## Architecture (voir aussi README.md et docs/tutoriel.md)

- `instrument/hp4194a.py` : `HP4194A` (pyvisa), `SimulatedInstrument` (inductance ou
  condensateur), `SweepSettings`. Le 4194A ne connaît pas `*IDN?` (utiliser `REV?`).
  Commandes reprises du VBA : `FNC1`, `SWT1/2`, `NOP=`, `START=`, `STOP=`, `ITM1..3`,
  `IMP2` (R-X), `SWTRG`, `TRIG`, `X?`, `A?`, `B?`.
- `model/` : `capture.py` (mesure en Z complexe, `ModelFit`), `component.py` (fiche +
  mesures + modèle de référence, format « RLCmeter component v2 », lit le v1),
  `library.py` (répertoires librairie / brouillons), `fit.py`, `spice.py`, `filter.py`.
- `controller/` : `main_controller.py`, `library_view.py` (proxy de tri / filtre),
  `acquisition.py` (QThread), `filter_controller.py`.
- `view/` : fenêtre principale (Session en haut, Librairie en bas), fiche de composant,
  fenêtre de filtre.
- `tests/` : 91 tests, interface comprise (sans écran), sur instrument simulé.

## Choix de conception à respecter

- Mesure toujours en **R-X**, stockée en impédance complexe ; Ls-Rs, |Z|-Theta, Cs-Rs dérivés.
- Inductance : Foster / Cauer, `x=[R0,L0,R1,L1,...,(Rp,Cp)]`, 1 à 3 cellules.
- Condensateur : `x=[ESR,ESL,C0,R1,C1,...,(Rf)]`, 0 à 2 branches R-C en parallèle sur C0.
  Usage visé : polypropylène, électrochimique, rares C0G gros boîtiers ; résonance dans
  100 Hz – 40 MHz.
- Ordre automatique par AIC avec `AIC_MARGIN = 10` (l'ordre le plus simple à moins de 10
  du meilleur), sinon des branches parasites apparaissent.
- Un composant porte plusieurs mesures, chaque mesure plusieurs modèles. Chaque mesure
  est enregistrée aussitôt en brouillon (`brouillons/`, ignoré par git).
- Librairie locale ; à terme partagée en **lecture seule**. Pas d'écritures simultanées à
  gérer (un seul analyseur).
- Fermeture : destruction ordonnée dans `main.py` (fenêtre puis contrôleur), modèles Qt
  parentés à leurs vues, slots en méthodes liées. Ne pas revenir en arrière : sinon
  plantage aléatoire en sortie.
- Tests d'interface : `helpers.get_app()` garde une référence globale sur `QApplication`,
  et `dispose(ctrl)` détruit les fenêtres en fin de test.

## Non validé sur l'appareil réel

- Liaison GPIB et ordre des commandes (ITM / IMP avant le déclenchement).
- Mode d'attente « Octet d'état » (bit 0 supposé) ; « Durée estimée » est le mode par défaut.
- Fits de condensateurs et Cauer sur mesures réelles.
- Librairie partagée en lecture seule sur un vrai partage réseau.

## Limites connues

- Pas de champ structuré pour les conditions de mesure.
- Visibilité des courbes non enregistrée.
- Pas de recherche dans la liste de composants de la fenêtre de filtre ; filtres non sauvegardés.
- Les sous-répertoires de la librairie sont lus mais plus affichés comme dossiers.
- `ressources/custom_options_ui.py` : fichier non suivi, d'origine inconnue de Claude.
