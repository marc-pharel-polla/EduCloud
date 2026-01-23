#!/usr/bin/env python3
"""
Wrapper libvirt pour utilisation SSH-only dans Docker
Permet d'utiliser le même code app.py avec ou sans Docker
"""
import os
import subprocess

# Vérifier si on est dans Docker
IN_DOCKER = os.path.exists('/.dockerenv')

if IN_DOCKER:
    print("🐳 Mode Docker détecté - Utilisation SSH pour tous les hôtes KVM")
    
    # Importer paramiko pour SSH
    try:
        import paramiko
        HAS_PARAMIKO = True
    except ImportError:
        HAS_PARAMIKO = False
        print("⚠️  paramiko non installé")

# Importer le vrai libvirt
try:
    import libvirt as _libvirt
    HAS_LIBVIRT = True
except ImportError:
    HAS_LIBVIRT = False
    print("⚠️  libvirt-python non installé (normal en mode Docker)")
    
    # Créer un mock minimal
    class LibvirtMock:
        libvirtError = Exception
        VIR_DOMAIN_RUNNING = 1
        VIR_DOMAIN_INTERFACE_ADDRESSES_SRC_AGENT = 0
        
        @staticmethod
        def open(uri):
            if 'ssh' not in uri:
                raise Exception(
                    f"Mode Docker: URI '{uri}' non supportée. "
                    "Utilisez uniquement des URIs SSH (qemu+ssh://...)"
                )
            raise Exception("libvirt-python non installé - SSH pur non implémenté")
    
    _libvirt = LibvirtMock()

# Exporter les fonctions/constantes nécessaires
libvirtError = _libvirt.libvirtError
VIR_DOMAIN_RUNNING = _libvirt.VIR_DOMAIN_RUNNING
VIR_DOMAIN_INTERFACE_ADDRESSES_SRC_AGENT = getattr(
    _libvirt, 'VIR_DOMAIN_INTERFACE_ADDRESSES_SRC_AGENT', 0
)

def open(uri):
    """Ouvre une connexion libvirt (SSH-only en mode Docker)"""
    if IN_DOCKER and uri == 'qemu:///system':
        raise Exception(
            "Mode Docker: Impossible d'accéder au KVM local. "
            "Utilisez un URI SSH vers l'hôte physique."
        )
    
    if not HAS_LIBVIRT:
        raise Exception(
            f"libvirt-python non installé. URI demandée: {uri}"
        )
    
    return _libvirt.open(uri)
