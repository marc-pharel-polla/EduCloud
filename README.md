# EduCloud 

Plateforme pédagogique de type **Infrastructure as a Service (IaaS)** permettant le déploiement et la gestion **automatisés** de machines virtuelles Linux à l’aide de **KVM**, **libvirt** et **cloud-init**.

---

## 📌 Présentation

**EduCloud** est un mini cloud académique conçu pour illustrer concrètement le fonctionnement d’un service IaaS. Il fournit une API REST et une interface web permettant de créer, démarrer, arrêter, supprimer et superviser des machines virtuelles sans intervention humaine lors de l’installation.

---

## 🎯 Objectifs du projet

* Mettre en pratique les concepts du cloud computing (IaaS)
* Automatiser le déploiement de machines virtuelles
* Utiliser KVM/QEMU avec libvirt
* Exploiter cloud-init pour une installation non interactive
* Centraliser la gestion des VM via une interface web

---

## 🏗️ Architecture générale

```
Utilisateur (Navigateur Web)
        │
        ▼
Interface Web (HTML / JavaScript)
        │
        ▼
Backend Flask (API REST)
        │
        ▼
Libvirt
        │
        ▼
QEMU / KVM
        │
        ▼
Machines Virtuelles (Ubuntu)
```

---

## ⚙️ Technologies utilisées

* Python 3
* Flask (API REST)
* Libvirt (bindings Python)
* QEMU / KVM
* virt-install
* cloud-init (Ubuntu autoinstall)
* qemu-img
* genisoimage

---

## 🚀 Fonctionnalités

### Gestion des machines virtuelles

* Création automatisée de VM
* Démarrage et arrêt des VM
* Suppression complète (VM + disque)
* Liste des VM existantes

### Déploiement automatisé

* Installation Ubuntu sans interaction humaine
* Création automatique d’un utilisateur
* Mot de passe chiffré
* Accès SSH immédiat
* Attribution automatique d’une adresse IP

### Supervision basique

* Utilisation CPU (%)
* Utilisation mémoire (%)
* Taille du disque virtuel

---

## 📦 Principe de déploiement d’une VM

1. Envoi des paramètres à l’API `/deploy`
2. Création d’un disque virtuel au format `qcow2`
3. Génération d’un ISO **cloud-init (cidata)** contenant :

   * utilisateur
   * mot de passe chiffré
   * clé SSH (optionnelle)
4. Lancement de `virt-install` avec :

   * ISO Ubuntu
   * ISO cloud-init
5. Démarrage automatique de la VM
6. Récupération automatique de l’adresse IP

➡️ L’installation est **entièrement non interactive**, conformément au modèle IaaS.

---

## ▶️ Installation et lancement

### Environnement virtuel Python

Le backend Python de **EduCloud IaaS** est exécuté dans un **environnement virtuel** afin d’isoler les dépendances du projet.

### Prérequis

* Système Linux avec virtualisation matérielle activée (KVM)

```bash
sudo dnf install libvirt qemu-kvm virt-install genisoimage cloud-utils
sudo systemctl enable --now libvirtd
```

### Création et activation de l’environnement virtuel

```bash
python3 -m venv venv
source venv/bin/activate
pip install flask libvirt-python
```

### Lancer l’application

```bash
python3 app.py
````

Interface web disponible à l’adresse :

```
http://localhost:5000
```

---

## 📚 Cas d’usage

* Projet académique en cloud computing
* Apprentissage de la virtualisation KVM
* Démonstration d’un mini cloud IaaS
* Base pédagogique pour des projets cloud avancés

---

## ⚠️ Limites actuelles

* Support principal : Ubuntu
* Supervision basique
* Pas de gestion multi-utilisateurs
* Pas de stockage distribué

---

## 🔮 Améliorations possibles

* Support Fedora / Debian
* Authentification utilisateur
* Réseau avancé (VLAN, bridges multiples)
* Snapshots de VM

---

## 👤 Auteur

Marc Pharel Polla
Projet académique – Cloud computing / Virtualisation

