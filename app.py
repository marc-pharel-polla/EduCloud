#!/usr/bin/env python3
"""
IaaS Multi-tenant avec SQLAlchemy ORM
VERSION MISE À JOUR pour support multi-fichiers HTML/JS
"""
import os
import subprocess
import libvirt
import time
import json
import secrets
import hashlib
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, g, send_from_directory
from flask_cors import CORS
import jwt
import shutil
import re

# Charger les variables d'environnement
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Import des models SQLAlchemy
from models import (
    Database, User, VM, Network, Billing,
    UserRepository, VMRepository, NetworkRepository, BillingRepository,
    seed_database
)

# ========================================
# CONFIGURATION FLASK
# ========================================

app = Flask(__name__,
            template_folder='templates',  # ✅ Dossier pour les HTML
            static_folder='static')        # ✅ Dossier pour les JS/CSS

CORS(app)

# Configuration
SECRET_KEY = os.getenv('SECRET_KEY', secrets.token_hex(32))

# Configuration Base de Données
DATABASE_URL = os.getenv(
    'DATABASE_URL',
    'sqlite:///Edu_Cloud.db'
)

BASE_IMG_DIR = os.environ.get('IMAGES_DIR', '/var/lib/educloud/images')
DISK_DIR = os.path.expanduser('~/.local/share/libvirt/images')

os.makedirs(BASE_IMG_DIR, exist_ok=True)
os.makedirs(DISK_DIR, exist_ok=True)

# Images disponibles
BASE_IMAGES = {
    'ubuntu-22.04': 'https://cloud-images.ubuntu.com/releases/22.04/release/ubuntu-22.04-server-cloudimg-amd64.img',
    'ubuntu-24.04': 'https://cloud-images.ubuntu.com/releases/24.04/release/ubuntu-24.04-server-cloudimg-amd64.img',
    'debian-12': 'https://cloud.debian.org/images/cloud/bookworm/latest/debian-12-generic-amd64.qcow2',
    'fedora-43': 'https://download.fedoraproject.org/pub/fedora/linux/releases/43/Cloud/x86_64/images/Fedora-Cloud-Base-Generic-43-1.6.x86_64.qcow2'
}

# Flavors avec prix
FLAVORS = {
    'S': {'vcpu': 1, 'ram_mb': 2048, 'disk_gb': 15, 'price_month': 2500, 'name': 'Small'},
    'M': {'vcpu': 2, 'ram_mb': 4096, 'disk_gb': 20, 'price_month': 3500, 'name': 'Medium'},
    'L': {'vcpu': 4, 'ram_mb': 8192, 'disk_gb': 40, 'price_month': 6500, 'name': 'Large'},
}

# Hôtes KVM
KVM_HOSTS = {
    'local': {
        'uri': 'qemu:///system',
        'name': 'Hôte Local',
        'disk_dir': DISK_DIR,
        'max_vcpu': 8,
        'max_ram_mb': 16384,
        'max_disk_gb': 200
    },
    'fedora-pmp': {
        'uri': 'qemu+ssh://polla@192.168.1.181/system',
        'name': 'Fedora PMP (Distant)',
        'disk_dir': '/var/lib/libvirt/images',
        
        # ✅ Spécifications réelles de votre PC
        'max_vcpu': 4,      # 4 vCPUs disponibles
        'max_ram_mb': 7835,  # ~7.7 GB RAM
        'max_disk_gb': 100,  # Ajustez selon l'espace disque disponible
        
        'priority': 2  # Utilisé si local est plein
    },
    
}

# Initialiser la base de données
db = Database(DATABASE_URL)

# ========================================
# ROUTES POUR SERVIR LES FICHIERS
# ========================================

@app.route('/')
def index():
    """Page d'accueil - Connexion"""
    return send_from_directory('templates', 'index.html')

@app.route('/<path:filename>')
def serve_files(filename):
    """Sert les fichiers HTML, JS et autres ressources"""
    # Fichiers HTML depuis templates/
    if filename.endswith('.html'):
        return send_from_directory('templates', filename)
    
    # Fichiers JS, CSS, etc. depuis static/
    return send_from_directory('static', filename)

# ========================================
# HELPERS
# ========================================

@app.before_request
def before_request():
    """Crée une session DB pour chaque requête"""
    g.db_session = db.get_session()

@app.teardown_request
def teardown_request(exception=None):
    """Ferme la session DB après chaque requête"""
    session = getattr(g, 'db_session', None)
    if session:
        session.close()

def hash_password(password):
    """Hash un mot de passe"""
    return hashlib.sha256(password.encode()).hexdigest()

def verify_password(password, password_hash):
    """Vérifie un mot de passe"""
    return hash_password(password) == password_hash

def create_token(user_id, username, is_admin=False):
    """Crée un JWT token"""
    from datetime import timezone
    payload = {
        'user_id': user_id,
        'username': username,
        'is_admin': is_admin,
        'exp': datetime.now(timezone.utc) + timedelta(days=7)  # ✅ Version non-dépréciée
    }
    return jwt.encode(payload, SECRET_KEY, algorithm='HS256')

def verify_token(token):
    """Vérifie et décode un JWT token"""
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=['HS256'])
    except:
        return None

def require_auth(f):
    """Décorateur pour protéger les routes"""
    def wrapper(*args, **kwargs):
        auth_header = request.headers.get('Authorization')
        if not auth_header or not auth_header.startswith('Bearer '):
            return jsonify({'error': 'Non autorisé'}), 401
        
        token = auth_header.split(' ')[1]
        payload = verify_token(token)
        if not payload:
            return jsonify({'error': 'Token invalide'}), 401
        
        g.user_id = payload['user_id']
        g.username = payload['username']
        g.is_admin = payload.get('is_admin', False)  # ✅ RÉCUPÈRE is_admin
        return f(*args, **kwargs)
    wrapper.__name__ = f.__name__
    return wrapper

# ========================================
# GESTION DES IMAGES
# ========================================

def get_base_image(image_name):
    """Récupère le chemin d'une image locale"""
    if image_name not in BASE_IMAGES:
        return None
    
    filename = f"{image_name}.qcow2"
    dest_path = os.path.join(BASE_IMG_DIR, filename)
    
    if os.path.exists(dest_path):
        print(f"✓ Image trouvée: {dest_path}")
        return dest_path
    else:
        print(f"❌ Image non trouvée: {dest_path}")
        return None

def list_available_images():
    """Liste les images réellement disponibles localement"""
    available = []
    for image_name in BASE_IMAGES:
        filename = f"{image_name}.qcow2"
        path = os.path.join(BASE_IMG_DIR, filename)
        if os.path.exists(path):
            try:
                size_mb = round(os.path.getsize(path) / (1024**2), 1)
                available.append({
                    'name': image_name,
                    'path': path,
                    'size_mb': size_mb,
                    'downloaded': True
                })
            except:
                pass
    return available

# ========================================
# GESTION DES RÉSEAUX
# ========================================

def get_user_network(user_id, host_id):
    """Récupère ou crée le réseau de l'utilisateur"""
    network_repo = NetworkRepository(g.db_session)
    network = network_repo.find_by_user_and_host(user_id, host_id)
    
    if network:
        return network
    
    network_name = f"net-user-{user_id}"
    subnet = f"10.{100 + user_id}.0.0/24"
    
    try:
        create_libvirt_network(network_name, subnet, host_id)
        network = network_repo.create(user_id, network_name, subnet, host_id)
        print(f"✓ Réseau créé: {network_name} ({subnet})")
        return network
    except Exception as e:
        print(f"❌ Erreur création réseau: {e}")
        raise

def create_libvirt_network(name, subnet, host_id):
    """Crée un réseau libvirt isolé"""
    conn = get_connection(host_id)[0]
    
    try:
        net = conn.networkLookupByName(name)
        if net.isActive():
            conn.close()
            return
    except:
        pass
    
    network_base = subnet.split('/')[0].rsplit('.', 1)[0]
    xml = f"""<network>
  <name>{name}</name>
  <forward mode='nat'>
    <nat><port start='1024' end='65535'/></nat>
  </forward>
  <bridge name='virbr{100 + hash(name) % 100}' stp='on' delay='0'/>
  <ip address='{network_base}.1' netmask='255.255.255.0'>
    <dhcp>
      <range start='{network_base}.10' end='{network_base}.250'/>
    </dhcp>
  </ip>
</network>"""
    
    net = conn.networkDefineXML(xml)
    net.setAutostart(True)
    net.create()
    conn.close()

# ========================================
# GESTION DES HÔTES KVM
# ========================================

def get_connection(host_id):
    """Connexion à un hôte KVM"""
    if host_id not in KVM_HOSTS:
        raise ValueError(f"Hôte inconnu: {host_id}")
    
    config = KVM_HOSTS[host_id]
    
    try:
        conn = libvirt.open(config['uri'])
        if conn is None:
            raise Exception(f"Impossible de se connecter à {config['name']}")
        return conn, config
    except Exception as e:
        print(f"❌ Erreur connexion {host_id}: {e}")
        raise

def get_host_resources(host_id):
    """Calcule les ressources disponibles"""
    conn, config = get_connection(host_id)
    
    total_vcpu = config['max_vcpu']
    total_ram = config['max_ram_mb']
    total_disk = config['max_disk_gb']
    
    used_vcpu = 0
    used_ram = 0
    
    for dom in conn.listAllDomains():
        try:
            info = dom.info()
            used_vcpu += info[3]
            used_ram += info[2] // 1024
        except:
            pass
    
    conn.close()
    
    return {
        'vcpu': {'total': total_vcpu, 'used': used_vcpu, 'available': total_vcpu - used_vcpu},
        'ram_mb': {'total': total_ram, 'used': used_ram, 'available': total_ram - used_ram},
        'disk_gb': {'total': total_disk, 'used': 0, 'available': total_disk}
    }

def select_best_host(flavor):
    """Sélectionne le meilleur hôte (least used strategy)"""
    flavor_config = FLAVORS[flavor]
    best_host = None
    best_score = -1
    
    for host_id in KVM_HOSTS:
        try:
            resources = get_host_resources(host_id)
            
            if (resources['vcpu']['available'] >= flavor_config['vcpu'] and
                resources['ram_mb']['available'] >= flavor_config['ram_mb'] and
                resources['disk_gb']['available'] >= flavor_config['disk_gb']):
                
                score = (resources['vcpu']['available'] / resources['vcpu']['total'] +
                        resources['ram_mb']['available'] / resources['ram_mb']['total']) / 2
                
                if score > best_score:
                    best_score = score
                    best_host = host_id
        except Exception as e:
            print(f"Erreur vérification hôte {host_id}: {e}")
            continue
    
    if not best_host:
        raise Exception("Aucun hôte disponible avec ressources suffisantes")
    
    return best_host

# ========================================
# CLOUD-INIT
# ========================================

def create_cloud_init_iso(name, hostname, user, passwd, sshkey, host_config):
    """Crée un ISO cloud-init"""
    salt = secrets.token_hex(8)
    passwd_hash = subprocess.check_output(
        ['openssl', 'passwd', '-6', '-salt', salt, passwd],
        text=True
    ).strip()
    
    ssh_block = ""
    if sshkey:
        ssh_block = f"\nssh_authorized_keys:\n  - {sshkey}"
    
    user_data = f"""#cloud-config
hostname: {hostname}
users:
  - name: {user}
    groups: sudo
    shell: /bin/bash
    sudo: ALL=(ALL) NOPASSWD:ALL
    lock_passwd: false{ssh_block}
chpasswd:
  list: |
    {user}:{passwd}
  expire: false
ssh_pwauth: true
packages:
  - qemu-guest-agent
runcmd:
  - ip link set enp1s0 up
  - dhclient enp1s0
  - systemctl enable qemu-guest-agent || true
  - systemctl start qemu-guest-agent || true
"""
    
    meta_data = f"instance-id: {hostname}\nlocal-hostname: {hostname}\n"
    
    network_config = """version: 2
ethernets:
  enp1s0:
    dhcp4: true
    dhcp6: false
"""
    
    iso_path = os.path.join(host_config['disk_dir'], f"{name}-seed.iso")
    
    import tempfile
    with tempfile.TemporaryDirectory() as tmpd:
        with open(os.path.join(tmpd, 'user-data'), 'w') as f:
            f.write(user_data)
        with open(os.path.join(tmpd, 'meta-data'), 'w') as f:
            f.write(meta_data)
        with open(os.path.join(tmpd, 'network-config'), 'w') as f:
            f.write(network_config)
        
        subprocess.run([
            'genisoimage', '-quiet', '-output', iso_path,
            '-volid', 'cidata', '-joliet', '-rock',
            os.path.join(tmpd, 'user-data'),
            os.path.join(tmpd, 'meta-data'),
            os.path.join(tmpd, 'network-config')
        ], check=True)
    
    return iso_path

def _get_vm_ip(dom):
    """Récupère l'IP d'une VM via qemu-guest-agent"""
    try:
        if not dom.isActive():
            return None
        
        ifaces = dom.interfaceAddresses(libvirt.VIR_DOMAIN_INTERFACE_ADDRESSES_SRC_AGENT, 0)
        for name, iface in ifaces.items():
            if name != 'lo' and iface['addrs']:
                for addr in iface['addrs']:
                    if addr['type'] == 0:
                        return addr['addr']
    except:
        pass
    return None

# ========================================
# ROUTES API - AUTHENTIFICATION
# ========================================

@app.route('/auth/register', methods=['POST'])
def register():
    """Inscription d'un nouvel utilisateur"""
    data = request.json
    username = data.get('username')
    password = data.get('password')
    email = data.get('email')
    
    if not username or not password:
        return jsonify({'error': 'Username et password requis'}), 400
    
    # Validation
    if len(username) < 3:
        return jsonify({'error': 'Username trop court (minimum 3 caractères)'}), 400
    
    if len(password) < 6:
        return jsonify({'error': 'Mot de passe trop court (minimum 6 caractères)'}), 400
    
    user_repo = UserRepository(g.db_session)
    
    if user_repo.find_by_username(username):
        return jsonify({'error': 'Utilisateur existe déjà'}), 409
    
    try:
        # Créer l'utilisateur
        user = user_repo.create(
            username=username,
            password_hash=hash_password(password),
            email=email,
            is_admin=False
        )
        
        print(f"✅ Nouvel utilisateur inscrit: {username} (ID: {user.id})")
        
        # ✅ AJOUT : Créer le token directement pour auto-login
        token = create_token(user.id, user.username, user.is_admin)
        
        # ✅ RETOUR : Token + infos user pour connexion auto
        return jsonify({
            'message': 'Compte créé avec succès',
            'user': user.to_dict(),
            'token': token,  # ✅ Token pour auto-login
            'username': username,
            'user_id': user.id,
            'is_admin': user.is_admin
        }), 201
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/auth/login', methods=['POST'])
def login():
    data = request.json
    username = data.get('username')
    password = data.get('password')
    
    user_repo = UserRepository(g.db_session)
    user = user_repo.find_by_username(username)
    
    if not user or not verify_password(password, user.password_hash):
        return jsonify({'error': 'Identifiants invalides'}), 401
    
    token = create_token(user.id, user.username, user.is_admin)  # ✅ PASSE is_admin
    return jsonify({
        'token': token,
        'username': username,
        'user_id': user.id,
        'is_admin': user.is_admin  # ✅ RETOURNE is_admin au frontend
    })

@app.route('/auth/me')
@require_auth
def get_current_user():
    """Retourne les infos de l'utilisateur connecté"""
    user_repo = UserRepository(g.db_session)
    user = user_repo.find_by_id(g.user_id)
    
    if not user:
        return jsonify({'error': 'Utilisateur non trouvé'}), 404
    
    return jsonify(user.to_dict())  # ✅ to_dict() inclut is_admin

# ========================================
# ROUTES API - RESOURCES
# ========================================

@app.route('/flavors')
def list_flavors():
    return jsonify([{'id': k, **v} for k, v in FLAVORS.items()])

@app.route('/hosts')
def list_hosts():
    """Liste les hôtes KVM disponibles"""
    return jsonify([
        {'id': k, 'name': v['name'], 'uri': v['uri']}
        for k, v in KVM_HOSTS.items()
    ])

@app.route('/hosts/status')
@require_auth
def hosts_status():
    """✅ NOUVEAU: Liste les hôtes KVM avec leur statut"""
    hosts_info = []
    
    for host_id, config in KVM_HOSTS.items():
        try:
            conn, _ = get_connection(host_id)
            resources = get_host_resources(host_id)
            
            vm_count = len(conn.listAllDomains())
            vm_running = len([d for d in conn.listAllDomains() if d.isActive()])
            
            conn.close()
            
            hosts_info.append({
                'id': host_id,
                'name': config['name'],
                'uri': config['uri'],
                'status': 'online',
                'vms_total': vm_count,
                'vms_running': vm_running,
                'resources': resources
            })
        except Exception as e:
            hosts_info.append({
                'id': host_id,
                'name': config['name'],
                'uri': config['uri'],
                'status': 'offline',
                'error': str(e)
            })
    
    return jsonify(hosts_info)

@app.route('/images')
def list_images():
    images = []
    for name, url in BASE_IMAGES.items():
        filename = f"{name}.qcow2"
        path = os.path.join(BASE_IMG_DIR, filename)
        
        is_downloaded = os.path.exists(path)
        size_mb = 0
        
        if is_downloaded:
            try:
                size_mb = round(os.path.getsize(path) / (1024**2), 1)
            except:
                pass
        
        images.append({
            'name': name,
            'url': url,
            'downloaded': is_downloaded,
            'size_mb': size_mb,
            'path': path if is_downloaded else None
        })
    
    return jsonify(images)

@app.route('/images/available')
def list_available_images_route():
    """Liste UNIQUEMENT les images disponibles localement"""
    try:
        available = list_available_images()
        return jsonify(available)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ========================================
# ROUTES API - VMS
# ========================================

@app.route('/vms', methods=['GET'])
@require_auth
def list_vms():
    """Liste les VMs de l'utilisateur connecté"""
    vm_repo = VMRepository(g.db_session)
    vms = vm_repo.find_by_user(g.user_id)
    
    result = []
    for vm in vms:
        vm_dict = vm.to_dict()
        
        if vm.flavor in FLAVORS:
            flavor = FLAVORS[vm.flavor]
            vm_dict['vcpu'] = flavor.get('vcpu', 0)
            vm_dict['ram_mb'] = flavor.get('ram_mb', 0)
        elif vm.flavor == 'admin-custom':
            try:
                conn, _ = get_connection(vm.host_id)
                dom = conn.lookupByName(vm.name)
                info = dom.info()
                vm_dict['vcpu'] = info[3]
                vm_dict['ram_mb'] = info[2] // 1024
                conn.close()
            except:
                vm_dict['vcpu'] = 0
                vm_dict['ram_mb'] = 0
        else:
            vm_dict['vcpu'] = 0
            vm_dict['ram_mb'] = 0
        
        try:
            conn, _ = get_connection(vm.host_id)
            dom = conn.lookupByName(vm.name)
            vm_dict['ip_address'] = _get_vm_ip(dom)
            
            info = dom.info()
            real_status = 'running' if info[0] == 1 else 'stopped'
            if real_status != vm.status:
                vm_repo.update_status(vm.id, real_status)
                vm_dict['status'] = real_status
            
            conn.close()
        except:
            vm_dict['ip_address'] = None
        
        result.append(vm_dict)
    
    return jsonify(result)

@app.route('/vms', methods=['POST'])
@require_auth
def create_vm():
    """Crée une nouvelle VM"""
    try:
        data = request.json
        
        # ✅ Nom affiché (ce que l'utilisateur tape)
        display_name = data.get('name', '').strip()
        
        # ✅ Validation du nom affiché
        if not display_name:
            return jsonify({'error': 'Nom de VM requis'}), 400
            
        if not re.match(r'^[a-zA-Z0-9-_]+$', display_name):
            return jsonify({'error': 'Nom invalide (utilisez seulement a-z, 0-9, - et _)'}), 400
        
        if len(display_name) > 50:
            return jsonify({'error': 'Nom trop long (maximum 50 caractères)'}), 400
        
        # ✅ Vérifier si l'utilisateur a déjà une VM avec ce nom affiché
        vm_repo = VMRepository(g.db_session)
        existing_vm = vm_repo.find_by_display_name_and_user(display_name, g.user_id)
        if existing_vm:
            return jsonify({
                'error': f'Vous avez déjà une VM nommée "{display_name}"',
                'suggestion': f'Essayez: {display_name}-2, {display_name}-v2, etc.'
            }), 409
        
        # ✅ Générer le nom technique unique
        # Format: user{id}_{display_name}_{timestamp}
        timestamp = int(time.time())
        name = f"user{g.user_id}_{display_name}_{timestamp}"
        
        image = data.get('image')
        if not image:
            return jsonify({'error': 'Image requise'}), 400
            
        user = data.get('user', 'ubuntu')
        password = data.get('password')
        if not password:
            return jsonify({'error': 'Mot de passe requis'}), 400
            
        sshkey = data.get('sshkey', '')

        # Pré-checks des outils
        for tool in ('virt-install', 'qemu-img', 'genisoimage'):
            if shutil.which(tool) is None:
                return jsonify({'error': f'Binary requis introuvable: {tool}'}), 500

        # Gestion flavor / ressources
        if g.is_admin:
            cpu = int(data.get('cpu', 2))
            ram_mb = int(data.get('ram', 4096))
            disk_gb = int(data.get('disk', 20))
            flavor = 'admin-custom'
            host_id = data.get('host', 'local')
        else:
            if 'flavor' not in data:
                return jsonify({'error': 'Flavor requis'}), 400
            flavor = data['flavor']
            if flavor not in FLAVORS:
                return jsonify({'error': 'Flavor invalide'}), 400
            cfg = FLAVORS[flavor]
            cpu = cfg['vcpu']
            ram_mb = cfg['ram_mb']
            disk_gb = cfg['disk_gb']
            host_id = select_best_host(flavor)

        # Réseau utilisateur
        network = get_user_network(g.user_id, host_id)

        # ✅ Créer entrée DB avec display_name
        vm = vm_repo.create(
            user_id=g.user_id,
            name=name,                    # Nom technique unique
            display_name=display_name,    # ✅ Nom affiché
            host_id=host_id,
            flavor=flavor,
            image=image,
            network_id=network.id,
            status='creating'
        )

        # Vérifier image
        base_image = get_base_image(image)
        if not base_image:
            vm_repo.update_status(vm.id, 'error')
            return jsonify({
                'error': f'Image {image} non disponible',
                'message': 'Téléchargez l\'image avec: ./download-images.sh'
            }), 400

        # Connexion hôte
        conn, host_config = get_connection(host_id)

        # Créer disque
        disk_path = os.path.join(host_config['disk_dir'], f"{name}.qcow2")
        try:
            r = subprocess.run([
                'qemu-img', 'create', '-f', 'qcow2', '-F', 'qcow2', '-b', base_image,
                disk_path, f"{disk_gb}G"
            ], capture_output=True, text=True, check=False)
            if r.returncode != 0:
                raise RuntimeError(f"qemu-img failed: {r.stderr.strip()}")
        except Exception as e:
            conn.close()
            vm_repo.update_status(vm.id, 'error')
            return jsonify({'error': 'Erreur création disque', 'detail': str(e)}), 500

        # Cloud-init
        try:
            seed_iso = create_cloud_init_iso(name, name, user, password, sshkey, host_config)
            if not os.path.exists(seed_iso):
                raise RuntimeError(f"ISO manquant: {seed_iso}")
        except Exception as e:
            conn.close()
            vm_repo.update_status(vm.id, 'error')
            return jsonify({'error': 'Erreur cloud-init', 'detail': str(e)}), 500

        # virt-install
        cmd = [
            'virt-install',
            '--connect', host_config['uri'],
            '--name', name,
            '--vcpus', str(cpu),
            '--memory', str(ram_mb),
            f'--disk=path={disk_path},format=qcow2,bus=virtio',
            f'--disk=path={seed_iso},device=cdrom',
            '--network', f'network={network.name},model=virtio',
            '--os-variant', 'ubuntu22.04',
            '--graphics', 'none',
            '--noautoconsole',
            '--import'
        ]

        try:
            r = subprocess.run(cmd, capture_output=True, text=True, check=False)
            if r.returncode != 0:
                err = r.stderr.strip() or r.stdout.strip()
                conn.close()
                vm_repo.update_status(vm.id, 'error')
                return jsonify({'error': 'virt-install failed', 'detail': err}), 500
        except Exception as e:
            conn.close()
            vm_repo.update_status(vm.id, 'error')
            return jsonify({'error': 'Erreur virt-install', 'detail': str(e)}), 500

        # Attendre confirmation
        created = False
        for _ in range(20):
            try:
                dom = conn.lookupByName(name)
                info = dom.info()
                if info[0] == libvirt.VIR_DOMAIN_RUNNING:
                    created = True
                    break
            except libvirt.libvirtError:
                time.sleep(1)
                continue

        if not created:
            domains = [d.name() for d in conn.listAllDomains()]
            conn.close()
            vm_repo.update_status(vm.id, 'error')
            return jsonify({'error': 'VM non confirmée', 'domains': domains}), 500

        # Succès
        vm_repo.update_status(vm.id, 'running')
        
        # Facturation (sauf admin)
        if not g.is_admin and flavor in FLAVORS:
            billing_repo = BillingRepository(g.db_session)
            price_hour = FLAVORS[flavor]['price_month'] / 730
            billing_repo.create(
                user_id=g.user_id, amount=price_hour,
                description=f"VM {display_name} - flavor {flavor}", vm_id=vm.id
            )

        conn.close()
        return jsonify(vm.to_dict()), 201

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/vms/<name>/start', methods=['POST'])
@require_auth
def start_vm(name):
    vm_repo = VMRepository(g.db_session)
    vm = vm_repo.find_by_name(name)
    
    if not vm:
        return jsonify({'error': 'VM non trouvée'}), 404
    
    if not g.is_admin and vm.user_id != g.user_id:  # ✅ UTILISE g.is_admin
        return jsonify({'error': 'Non autorisé'}), 403
    
    try:
        conn, _ = get_connection(vm.host_id)
        dom = conn.lookupByName(name)
        if not dom.isActive():
            dom.create()
        conn.close()
        vm_repo.update_status(vm.id, 'running')
        return jsonify({'message': f'VM {name} démarrée', 'status': 'running'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/vms/<name>/stop', methods=['POST'])
@require_auth
def stop_vm(name):
    vm_repo = VMRepository(g.db_session)
    vm = vm_repo.find_by_name(name)
    
    if not vm:
        return jsonify({'error': 'VM non trouvée'}), 404
    
    if not g.is_admin and vm.user_id != g.user_id:
        return jsonify({'error': 'Non autorisé'}), 403
    
    try:
        conn, _ = get_connection(vm.host_id)
        dom = conn.lookupByName(name)
        if dom.isActive():
            dom.shutdown()
        conn.close()
        vm_repo.update_status(vm.id, 'stopped')
        return jsonify({'message': f'VM {name} arrêtée', 'status': 'stopped'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/vms/<name>', methods=['DELETE'])
@require_auth
def delete_vm(name):
    """Supprime une VM"""
    vm_repo = VMRepository(g.db_session)
    vm = vm_repo.find_by_name(name)
    
    if not vm:
        return jsonify({'error': 'VM non trouvée'}), 404
    
    if not g.is_admin and vm.user_id != g.user_id:
        return jsonify({'error': 'Non autorisé'}), 403
    
    try:
        conn, host_config = get_connection(vm.host_id)
        
        # Arrêter et supprimer de libvirt
        try:
            dom = conn.lookupByName(name)
            if dom.isActive():
                dom.destroy()
                time.sleep(1)
            dom.undefine()
        except libvirt.libvirtError as e:
            if 'Domain not found' not in str(e):
                raise
        
        # Supprimer les disques
        disk_path = os.path.join(host_config['disk_dir'], f"{name}.qcow2")
        seed_path = os.path.join(host_config['disk_dir'], f"{name}-seed.iso")
        
        deleted_files = []
        
        if os.path.exists(disk_path):
            os.remove(disk_path)
            deleted_files.append(disk_path)
        
        if os.path.exists(seed_path):
            os.remove(seed_path)
            deleted_files.append(seed_path)
        
        conn.close()
        
        # Supprimer de la DB
        vm_repo.delete(vm.id)
        
        # Facturation (note de suppression)
        if not g.is_admin and vm.flavor in FLAVORS:
            billing_repo = BillingRepository(g.db_session)
            billing_repo.create(
                user_id=g.user_id,
                amount=0,
                description=f"VM {name} supprimée - flavor {vm.flavor}",
                vm_id=None
            )
        
        return jsonify({
            'message': f'VM {name} supprimée',
            'deleted': {'name': name, 'files': deleted_files}
        }), 200
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/vms/<name>/test-ssh', methods=['POST'])
@require_auth
def test_ssh(name):
    """Teste la connexion SSH vers une VM"""
    vm_repo = VMRepository(g.db_session)
    vm = vm_repo.find_by_name(name)
    
    if not vm:
        return jsonify({'error': 'VM non trouvée'}), 404
    
    if not g.is_admin and vm.user_id != g.user_id:
        return jsonify({'error': 'Non autorisé'}), 403
    
    try:
        conn, _ = get_connection(vm.host_id)
        dom = conn.lookupByName(name)
        ip = _get_vm_ip(dom)
        conn.close()
        
        if not ip:
            return jsonify({'success': False, 'error': 'IP non disponible'}), 400
        
        import socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(3)
        result = sock.connect_ex((ip, 22))
        sock.close()
        
        if result == 0:
            return jsonify({
                'success': True,
                'ip': ip,
                'port': 22,
                'message': f'SSH accessible sur {ip}:22'
            })
        else:
            return jsonify({
                'success': False,
                'error': 'Port SSH non accessible',
                'ip': ip
            })
            
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

# ========================================
# ROUTES API - FACTURATION
# ========================================

@app.route('/billing')
@require_auth
def get_billing():
    """Historique de facturation de l'utilisateur"""
    billing_repo = BillingRepository(g.db_session)
    bills = billing_repo.find_by_user(g.user_id)
    total = billing_repo.get_total_by_user(g.user_id)
    
    return jsonify({
        'bills': [b.to_dict() for b in bills],
        'total': round(total, 2)
    })

# ========================================
# ROUTES API - ADMIN UNIQUEMENT
# ========================================

@app.route('/admin/users', methods=['GET'])
@require_auth
def admin_list_users():
    """Liste tous les utilisateurs (admin uniquement)"""
    print(f"🔍 DEBUG: User {g.username} (ID: {g.user_id}) demande la liste users")
    print(f"🔍 DEBUG: is_admin = {g.is_admin}")
    
    if not g.is_admin:
        print("❌ DEBUG: Accès refusé - pas admin")
        return jsonify({'error': 'Accès réservé aux administrateurs'}), 403
    
    try:
        user_repo = UserRepository(g.db_session)
        users = user_repo.get_all()
        
        print(f"✅ DEBUG: {len(users)} utilisateurs trouvés en DB")
        
        users_data = []
        for user in users:
            print(f"   - Processing user: {user.username} (ID: {user.id})")
            
            vm_repo = VMRepository(g.db_session)
            vms = vm_repo.find_by_user(user.id)
            
            billing_repo = BillingRepository(g.db_session)
            total_billing = billing_repo.get_total_by_user(user.id)
            
            user_dict = {
                **user.to_dict(),
                'vm_count': len(vms),
                'total_billing': round(total_billing, 2)
            }
            
            print(f"     → {user.username}: {len(vms)} VMs, {total_billing} FCFA")
            users_data.append(user_dict)
        
        print(f"✅ DEBUG: Retour de {len(users_data)} utilisateurs au frontend")
        return jsonify(users_data)
        
    except Exception as e:
        import traceback
        print("❌ DEBUG: Erreur dans admin_list_users:")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/admin/users', methods=['POST'])
@require_auth
def admin_create_user():
    """Créer un utilisateur (admin uniquement)"""
    if not g.is_admin:
        return jsonify({'error': 'Accès réservé aux administrateurs'}), 403
    
    data = request.json
    username = data.get('username')
    password = data.get('password')
    email = data.get('email')
    
    if not username or not password:
        return jsonify({'error': 'Username et password requis'}), 400
    
    user_repo = UserRepository(g.db_session)
    
    if user_repo.find_by_username(username):
        return jsonify({'error': 'Utilisateur existe déjà'}), 409
    
    try:
        user = user_repo.create(
            username=username,
            password_hash=hash_password(password), 
            email=email,
            is_admin=False  # Les users créés par admin ne sont pas admin par défaut
        )
        
        print(f"✅ Admin {g.username} a créé l'utilisateur {username}")
        
        return jsonify({
            'message': f'Utilisateur {username} créé',
            'user': user.to_dict()
        }), 201
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/admin/users/<int:user_id>', methods=['DELETE'])
@require_auth
def admin_delete_user(user_id):
    """Supprimer un utilisateur (admin uniquement)"""
    if not g.is_admin:
        return jsonify({'error': 'Accès réservé aux administrateurs'}), 403
    
    user_repo = UserRepository(g.db_session)
    user = user_repo.find_by_id(user_id)
    
    if not user:
        return jsonify({'error': 'Utilisateur non trouvé'}), 404
    
    if user.username == 'admin':
        return jsonify({'error': 'Impossible de supprimer le compte admin'}), 403
    
    try:
        # Supprimer toutes les VMs de l'utilisateur
        vm_repo = VMRepository(g.db_session)
        user_vms = vm_repo.find_by_user(user_id)
        
        for vm in user_vms:
            try:
                conn, host_config = get_connection(vm.host_id)
                try:
                    dom = conn.lookupByName(vm.name)
                    if dom.isActive():
                        dom.destroy()
                    dom.undefine()
                except:
                    pass
                
                disk_path = os.path.join(host_config['disk_dir'], f"{vm.name}.qcow2")
                seed_path = os.path.join(host_config['disk_dir'], f"{vm.name}-seed.iso")
                
                if os.path.exists(disk_path):
                    os.remove(disk_path)
                if os.path.exists(seed_path):
                    os.remove(seed_path)
                
                conn.close()
            except Exception as e:
                print(f"Erreur suppression VM {vm.name}: {e}")
        
        # Supprimer l'utilisateur (cascade supprime VMs, networks, billing)
        g.db_session.delete(user)
        g.db_session.commit()
        
        return jsonify({
            'message': f'Utilisateur {user.username} supprimé',
            'vms_deleted': len(user_vms)
        }), 200
        
    except Exception as e:
        g.db_session.rollback()
        return jsonify({'error': str(e)}), 500

@app.route('/admin/users/<int:user_id>/reset-password', methods=['POST'])
@require_auth
def admin_reset_password(user_id):
    """Réinitialiser le mot de passe d'un utilisateur"""
    if not g.is_admin:
        return jsonify({'error': 'Accès réservé aux administrateurs'}), 403
    
    data = request.json
    new_password = data.get('password')
    
    if not new_password:
        return jsonify({'error': 'Nouveau mot de passe requis'}), 400
    
    user_repo = UserRepository(g.db_session)
    user = user_repo.find_by_id(user_id)
    
    if not user:
        return jsonify({'error': 'Utilisateur non trouvé'}), 404
    
    try:
        user.password_hash = hash_password(new_password)
        g.db_session.commit()
        
        return jsonify({
            'message': f'Mot de passe de {user.username} réinitialisé'
        }), 200
    except Exception as e:
        g.db_session.rollback()
        return jsonify({'error': str(e)}), 500

# ========================================
# MAIN
# ========================================

if __name__ == '__main__':
    print("=" * 60)
    print("🎓 Edu-Cloud IaaS Multi-tenant v3.0")
    print("VERSION MISE À JOUR - Structure modulaire")
    print("=" * 60)
    
    # Initialiser la base de données
    db.create_tables()
    seed_database(db)
    
    print(f"✓ {len(FLAVORS)} flavors disponibles")
    print(f"✓ {len(KVM_HOSTS)} hôtes KVM configurés")
    print("=" * 60)
    print("\n🔐 Compte administrateur:")
    print("  Username: admin")
    print("  Password: admin123")
    print("\n🌐 URLs:")
    print("  Frontend: http://localhost:5000")
    print("  API:      http://localhost:5000/api/*")
    print("\n📁 Structure:")
    print("  templates/index.html  → Page de connexion")
    print("  templates/user.html   → Interface utilisateur")
    print("  templates/admin.html  → Interface administrateur")
    print("  static/api.js         → Utilitaires API")
    print("  static/user-app.js    → Logique utilisateur")
    print("  static/admin-app.js   → Logique admin")
    print("=" * 60)
    app.run(host='0.0.0.0', port=5000, debug=True)
    
