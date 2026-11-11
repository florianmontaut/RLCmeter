# RLCmeter — tutoriel

RLCmeter pilote un analyseur d'impédance **HP 4194A** en GPIB, range les mesures dans une
librairie, ajuste des modèles d'inductance et estime la réponse d'un filtre construit avec
les composants mesurés.

## 1. Faire une mesure

1. Dans le panneau **Acquisition** (à droite), choisir la liaison : `Simulation`
   (inductance) ou `Simulation (condensateur)` pour essayer sans appareil, `GPIB` avec
   l'adresse de l'analyseur (17 par défaut).
2. **Tester la liaison** : la ligne *Appareil* affiche la réponse de l'analyseur.
3. Régler la plage de fréquence, le nombre de points (401 au plus) et le temps
   d'intégration. La *durée estimée* du balayage est affichée.
4. **Mesurer** (F5). Le bouton devient *Annuler* pendant le balayage.

La mesure est faite en R-X et enregistrée en impédance complexe. Le sélecteur
**Affichage** (Ls-Rs, |Z|-Theta, Cs-Rs) ne fait que changer la présentation.

## 2. Session et librairie

Le panneau de gauche est en deux parties.

**Session** (en haut) : les mesures faites depuis l'ouverture du logiciel. Chacune est
enregistrée aussitôt dans le répertoire des *brouillons* : rien n'est perdu si le
logiciel est fermé. *Fichier > Brouillons des sessions précédentes* les réaffiche.

**Librairie** (en bas) : les composants caractérisés. Un composant regroupe :

- sa **fiche** : type, technologie, fabricant, référence fabricant, code Fay, valeur
  nominale, conditions de mesure, commentaire. Tous les champs peuvent rester vides ;
- une ou plusieurs **mesures** (conditions différentes, autre échantillon) ;
- pour chaque mesure, un ou plusieurs **modèles** (par exemple un par sous-bande).

Un modèle reste toujours attaché à la mesure qui le justifie.

**Ajouter à la librairie** (Ctrl+L) range la mesure de session sélectionnée : comme
nouveau composant, dont on remplit la fiche, ou comme nouvelle mesure d'un composant déjà
présent. Le type est proposé d'après la mesure ; technologie et fabricant proposent les
valeurs déjà utilisées dans la librairie.

**Retrouver un composant** :

- le champ de recherche porte sur toute la fiche (plusieurs mots : tous doivent y être) ;
- les trois listes filtrent par type, technologie et fabricant ; *(non renseigné)* montre
  les fiches à compléter ;
- un clic sur un en-tête de colonne trie (la colonne *Valeur* trie numériquement) ;
- un double-clic sur un composant ouvre sa fiche.

Sélectionner un composant trace ses mesures ; cocher une mesure la garde tracée.
`F2` renomme une mesure ou un modèle.

Le **modèle de référence** d'un composant (case à cocher dans les réglages du modèle,
icône distincte dans l'arborescence) est celui proposé par défaut à la réutilisation :
création de filtre, export, valeur affichée quand la valeur nominale est vide.

Les répertoires de la librairie et des brouillons se choisissent dans
*Utilitaires > Options*. Les sous-répertoires de la librairie sont lus eux aussi.
*Fichier > Ouvrir* ouvre un fichier de composant situé ailleurs ; *Sauvegarder sous* en
fait une copie.

## 3. Ajuster un modèle

Sélectionner une mesure (session ou librairie) puis **Ajuster un modèle** (Ctrl+M).

Le type proposé dépend de la mesure : *Condensateur* si elle est capacitive en bas de
bande, sinon le type d'inductance choisi dans les options.

- **Plage de fréquence** : dans la table, ou en déplaçant la zone colorée du graphe.
- **Ordre automatique** : essaie les ordres possibles et garde le plus simple qui suffit
  (critère AIC).

**Inductance** — Foster ou Cauer (identiques avec une seule cellule R-L) :
R0 + L0 en série avec 1 à 3 cellules R-L, qui traduisent la résistance qui monte avec la
fréquence (effet de peau, de proximité). *Capacité parallèle* : à activer si la résonance
propre est dans la plage.

**Condensateur** — ESR + ESL en série avec C0, plus 0 à 2 branches R-C en parallèle sur C0 :

- 0 branche : simple RLC série (polypropylène, céramique C0G) ;
- 1 ou 2 branches : capacité et pertes qui varient avec la fréquence (électrochimique) ;
- *Résistance de fuite* : résistance en parallèle sur C0, à activer si les pertes en
  basse fréquence sont visibles.

L'ESR et l'ESL sont déterminées à la résonance série : si elle est hors de la plage du
fit, la ligne *Résonance série* le signale et l'ESL n'est pas fiable.

Le fit est relancé à chaque changement. **Exporter .subckt** produit un sous-circuit
utilisable dans LTspice.

## 4. Créer un filtre

*Utilitaires > Création de filtre* ouvre une fenêtre à part.

1. Choisir la **topologie** : L, T ou Pi.
2. Pour chaque branche, choisir un **composant** de la librairie ou de la session :
   « ★ nom » (son modèle de référence), une de ses mesures (interpolée), un autre de ses
   modèles, ou un composant idéal R, L ou C dont on donne la valeur.
3. Régler les résistances de **source** et de **charge**.

Le graphe du haut donne le **gain d'insertion** (tension sur la charge avec le filtre,
rapportée à la tension sans filtre), celui du bas la phase. Le tableau donne la coupure à
−3 dB, le gain à la fréquence d'évaluation, l'atténuation maximale et le pic de résonance.

Le calcul n'est fait que sur la bande de fréquence commune à tous les composants.

## Raccourcis

| Touche | Action |
|---|---|
| F5 | Mesurer / annuler |
| Ctrl+M | Ajuster un modèle |
| Ctrl+L | Ajouter à la librairie |
| Ctrl+O | Ouvrir un fichier de composant |
| Ctrl+S | Sauvegarder le composant sous |
| Suppr | Supprimer la capture ou le modèle |
| F1 | Ce tutoriel |
