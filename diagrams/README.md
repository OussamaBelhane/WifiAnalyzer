# 📊 WifiAnalyzer - Diagrammes Mermaid

Diagrammes simplifiés documentant l'architecture du projet **WifiAnalyzer**.

## 📁 Diagrammes Disponibles

### 1. 🏗️ Diagramme de Classes
**Fichier** : `class_diagram.mmd`

Montre les 4 classes principales et leurs relations :
- **NetworkAnalyzerApp** : Interface GUI
- **NetworkScanner** : Scan réseau
- **WiFiBlocker** : Blocage d'appareils
- **DatabaseManager** : Stockage (Neo4j/JSON)

---

### 2. 🔄 Diagramme de Séquence - Scan
**Fichier** : `sequence_scan.mmd`

Flux simplifié du scan réseau :
1. Utilisateur démarre le scan
2. Scanner exécute ARP + ICMP ping
3. Identification et lookup des vendeurs
4. Sauvegarde en base de données
5. Affichage des résultats

---

### 3. 🚫 Diagramme de Séquence - Blocage
**Fichier** : `sequence_block.mmd`

Opérations de blocage/déblocage :
- **Bloquer** : Démarrage thread ARP spoofing
- **Débloquer** : Arrêt du thread

---

### 4. 🧩 Diagramme de Composants
**Fichier** : `component_diagram.mmd`

Architecture simple en 4 couches :
- **Interface** : GUI CustomTkinter
- **Logique** : Scanner + Blocker
- **Stockage** : Database Manager (Neo4j/JSON)
- **Externe** : Réseau local + Base OUI

---

### 5. 👤 Diagramme de Cas d'Utilisation
**Fichier** : `use_case_diagram.mmd`

7 fonctionnalités principales :
- Scanner le réseau
- Voir les appareils
- Gérer les appareils (Connu/Inconnu)
- Bloquer/Débloquer
- Voir l'historique
- Auto-scan périodique

---

### 6. 📊 Diagramme de Flux de Données
**Fichier** : `data_flow_diagram.mmd`

Circulation des données :
- **Entrées** : Commandes utilisateur, réseau
- **Processus** : Scan, gestion, blocage, affichage
- **Stockage** : Historique, statuts, blocklist

---

### 7. 🔄 Diagramme d'États
**Fichier** : `state_diagram.mmd`

États principaux de l'application :
- **Initialisation** : Chargement des ressources
- **Prêt** : Idle ↔ Scan
- **Blocage** : Thread ARP spoofing actif
- **Historique** : Consultation des données

---

## 🛠️ Visualisation

### GitHub
Les fichiers `.mmd` s'affichent automatiquement sur GitHub.

### Mermaid Live Editor
1. Ouvrir [mermaid.live](https://mermaid.live)
2. Copier le contenu d'un fichier
3. Visualiser en temps réel

### VS Code
Installer l'extension **Mermaid Preview** :
```bash
ext install bierner.markdown-mermaid
```

---

## 📝 Note

Ces diagrammes sont **simplifiés** pour donner une vue d'ensemble claire de l'architecture sans entrer dans les détails d'implémentation.
