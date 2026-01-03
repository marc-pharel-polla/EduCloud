
import os
import subprocess
import libvirt
import time
import json
import secrets
import hashlib
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, g
from flask_cors import CORS
import jwt

# Charger les variables d'environnement depuis .env
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv non installé, utiliser les variables d'environnement système

# Import des models SQLAlchemy
from models import (
    Database, User, VM, Network, Billing,
    UserRepository, VMRepository, NetworkRepository, BillingRepository,
    seed_database
)

app = Flask(__name__)
CORS(app)

# Configuration
SECRET_KEY = os.getenv('SECRET_KEY', secrets.token_hex(32))

# Configuration Base de Données
# IMPORTANT : Utilisez vos propres identifiants
DATABASE_URL = os.getenv(
    'DATABASE_URL',
    'mysql+pymysql://iaas_inf4107:TPinf4107@localhost/Edu_Cloud'
)

BASE_IMG_DIR = os.path.expanduser('~/Codes/base-images')
DISK_DIR = os.path.expanduser('~/.local/share/libvirt/images')

os.makedirs(BASE_IMG_DIR, exist_ok=True)
os.makedirs(DISK_DIR, exist_ok=True)

# Images disponibles
BASE_IMAGES = {
    'ubuntu-22.04': 'https://cloud-images.ubuntu.com/releases/22.04/release/ubuntu-22.04-server-cloudimg-amd64.img',
    'ubuntu-24.04': 'https://cloud-images.ubuntu.com/releases/24.04/release/ubuntu-24.04-server-cloudimg-amd64.img',
    'debian-12': 'https://cloud.debian.org/images/cloud/bookworm/latest/debian-12-generic-amd64.qcow2',
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
    }
}

# Initialiser la base de données
db = Database(DATABASE_URL)

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

def create_token(user_id, username):
    """Crée un JWT token"""
    payload = {
        'user_id': user_id,
        'username': username,
        'exp': datetime.utcnow() + timedelta(days=7)
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
        return f(*args, **kwargs)
    wrapper.__name__ = f.__name__
    return wrapper

# ========================================
# GESTION DES IMAGES
# ========================================

def get_base_image(image_name):
    """
    Récupère le chemin d'une image locale
    Cherche d'abord .qcow2, puis .img
    """
    if image_name not in BASE_IMAGES:
        return None
    
    # Essayer .qcow2
    filename_qcow2 = f"{image_name}.qcow2"
    path_qcow2 = os.path.join(BASE_IMG_DIR, filename_qcow2)
    if os.path.exists(path_qcow2):
        print(f"✓ Image trouvée: {path_qcow2}")
        return path_qcow2
    
    # Essayer .img
    filename_img = f"{image_name}.img"
    path_img = os.path.join(BASE_IMG_DIR, filename_img)
    if os.path.exists(path_img):
        print(f"✓ Image trouvée: {path_img}")
        return path_img
    
    print(f"❌ Image non trouvée: {image_name}")
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
    """Récupère ou crée le réseau de l'utilisateur (avec ORM)"""
    network_repo = NetworkRepository(g.db_session)
    
    # Chercher le réseau existant
    network = network_repo.find_by_user_and_host(user_id, host_id)
    
    if network:
        return network
    
    # Créer un nouveau réseau
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
    conn = libvirt.open(config['uri'])
    return conn, config

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
    """Sélectionne le meilleur hôte"""
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
  - systemctl enable qemu-guest-agent
  - systemctl start qemu-guest-agent
"""
    
    meta_data = f"instance-id: {hostname}\nlocal-hostname: {hostname}\n"
    network_config = "version: 2\nethernets:\n  eth0:\n    dhcp4: true\n"
    
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

# ========================================
# ROUTES API
# ========================================

@app.route('/')
def index():
    try:
        with open('./templates/index.html', 'r') as f:
            return f.read()
    except:
        return jsonify({'message': 'IaaS API v2 avec SQLAlchemy'})

# Authentification
@app.route('/auth/register', methods=['POST'])
def register():
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
        user = user_repo.create(username, hash_password(password), email)
        return jsonify({'message': 'Utilisateur créé', 'user': user.to_dict()}), 201
    except Exception as e:
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
    
    token = create_token(user.id, user.username)
    return jsonify({'token': token, 'username': username, 'user': user.to_dict()})

# Flavors
@app.route('/flavors')
def list_flavors():
    return jsonify([{'id': k, **v} for k, v in FLAVORS.items()])

# Hosts (liste des hôtes KVM disponibles)
@app.route('/hosts')
def list_hosts():
    """Liste les hôtes KVM disponibles"""
    return jsonify([
        {'id': k, 'name': v['name'], 'uri': v['uri']}
        for k, v in KVM_HOSTS.items()
    ])

# Images
@app.route('/images')
def list_images():
    """Liste les images avec support .img et .qcow2"""
    images = []
    for name, url in BASE_IMAGES.items():
        # Chercher .qcow2
        filename_qcow2 = f"{name}.qcow2"
        path_qcow2 = os.path.join(BASE_IMG_DIR, filename_qcow2)
        
        # Chercher .img
        filename_img = f"{name}.img"
        path_img = os.path.join(BASE_IMG_DIR, filename_img)
        
        is_downloaded = False
        size_mb = 0
        actual_path = None
        
        if os.path.exists(path_qcow2):
            is_downloaded = True
            actual_path = path_qcow2
            try:
                size_mb = round(os.path.getsize(path_qcow2) / (1024**2), 1)
            except:
                pass
        elif os.path.exists(path_img):
            is_downloaded = True
            actual_path = path_img
            try:
                size_mb = round(os.path.getsize(path_img) / (1024**2), 1)
            except:
                pass
        
        images.append({
            'name': name,
            'url': url,
            'downloaded': is_downloaded,
            'size_mb': size_mb,
            'path': actual_path
        })
    
    return jsonify(images)

@app.route('/images/download/<image_name>', methods=['POST'])
def download_image_manually(image_name):
    if image_name not in BASE_IMAGES:
        return jsonify({'error': 'Image inconnue'}), 404
    
    filename = f"{image_name}.qcow2"
    dest_path = os.path.join(BASE_IMG_DIR, filename)
    
    if os.path.exists(dest_path):
        return jsonify({'message': 'Image déjà téléchargée', 'path': dest_path})
    
    try:
        import threading
        
        def download_async():
            download_base_image(image_name)
        
        thread = threading.Thread(target=download_async)
        thread.start()
        
        return jsonify({
            'message': f'Téléchargement de {image_name} démarré',
            'status': 'downloading'
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500 

# VMs
@app.route('/vms', methods=['GET'])
@require_auth
def list_vms():
    """Liste les VMs de l'utilisateur connecté (isolation stricte)"""
    vm_repo = VMRepository(g.db_session)
    vms = vm_repo.find_by_user(g.user_id)
    
    result = []
    for vm in vms:
        vm_dict = vm.to_dict()
        flavor = FLAVORS.get(vm.flavor, {})
        vm_dict['vcpu'] = flavor.get('vcpu', 0)
        vm_dict['ram_mb'] = flavor.get('ram_mb', 0)
        result.append(vm_dict)
    
    return jsonify(result)

@app.route('/vms', methods=['POST'])
@require_auth
def create_vm():
    try:
        data = request.json
        name = data['name']
        flavor = data['flavor']
        image = data['image']
        user = data.get('user', 'ubuntu')
        password = data['password']
        sshkey = data.get('sshkey', '')
        
        if flavor not in FLAVORS:
            return jsonify({'error': 'Flavor invalide'}), 400
        
        flavor_config = FLAVORS[flavor]
        host_id = select_best_host(flavor)
        
        # Réseau utilisateur
        network = get_user_network(g.user_id, host_id)
        
        # Créer la VM dans la DB
        vm_repo = VMRepository(g.db_session)
        vm = vm_repo.create(
            user_id=g.user_id,
            name=name,
            host_id=host_id,
            flavor=flavor,
            image=image,
            network_id=network.id,
            status='creating'
        )
        
        # Récupérer l'image locale
        base_image = get_base_image(image)
        if not base_image:
            return jsonify({
                'error': f'Image {image} non disponible localement',
                'message': 'Téléchargez d\'abord l\'image avec: ./download-images.sh',
                'url': BASE_IMAGES.get(image)
            }), 400
        
        # Créer le disque
        conn, host_config = get_connection(host_id)
        disk_path = os.path.join(host_config['disk_dir'], f"{name}.qcow2")
        subprocess.run([
            'qemu-img', 'create', '-f', 'qcow2',
            '-F', 'qcow2', '-b', base_image,
            disk_path, f"{flavor_config['disk_gb']}G"
        ], check=True)
        
        # Cloud-init
        seed_iso = create_cloud_init_iso(name, name, user, password, sshkey, host_config)
        
        # Créer la VM
        cmd = [
            'virt-install',
            '--connect', host_config['uri'],
            '--name', name,
            '--vcpus', str(flavor_config['vcpu']),
            '--memory', str(flavor_config['ram_mb']),
            f'--disk=path={disk_path},format=qcow2,bus=virtio',
            f'--disk=path={seed_iso},device=cdrom',
            '--network', f'network={network.name},model=virtio',
            '--os-variant', 'ubuntu22.04',
            '--graphics', 'none',
            '--noautoconsole',
            '--import'
        ]
        
        subprocess.run(cmd, check=True)
        
        # Mettre à jour le statut
        vm_repo.update_status(vm.id, 'running')
        
        # Facturation
        billing_repo = BillingRepository(g.db_session)
        price_hour = flavor_config['price_month'] / 730
        billing_repo.create(
            user_id=g.user_id,
            amount=price_hour,
            description=f"VM {name} - flavor {flavor}",
            vm_id=vm.id
        )
        
        conn.close()
        
        return jsonify(vm.to_dict()), 201
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/vms/<n>/start', methods=['POST'])
@require_auth
def start_vm(name):
    vm_repo = VMRepository(g.db_session)
    vm = vm_repo.find_by_name(name)
    
    if not vm or vm.user_id != g.user_id:
        return jsonify({'error': 'VM non trouvée'}), 404
    
    try:
        conn, _ = get_connection(vm.host_id)
        dom = conn.lookupByName(name)
        if not dom.isActive():
            dom.create()
        conn.close()
        vm_repo.update_status(vm.id, 'running')
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/admin/vms', methods=['POST'])
@require_auth
def admin_create_vm():
    """Admin peut créer une VM avec specs custom (pas de flavor)"""
    if g.username != 'admin':
        return jsonify({'error': 'Accès réservé aux administrateurs'}), 403
    
    try:
        data = request.json
        name = data['name']
        image = data['image']
        host_id = data.get('host', 'local')
        cpu = int(data['cpu'])
        ram = int(data['ram']) * 1024  # Convertir en MB
        disk = int(data['disk'])
        user = data.get('user', 'ubuntu')
        password = data['password']
        sshkey = data.get('sshkey', '').strip()
        
        print(f"\n{'='*50}")
        print(f"[ADMIN] Création VM {name}")
        print(f"{'='*50}")
        
        # Vérifier que la VM n'existe pas
        conn, host_config = get_connection(host_id)
        try:
            conn.lookupByName(name)
            conn.close()
            return jsonify({'error': 'VM existe déjà'}), 409
        except:
            pass
        
        # Récupérer l'image
        base_image = get_base_image(image)
        if not base_image:
            conn.close()
            return jsonify({
                'error': f'Image {image} non disponible',
                'message': 'Téléchargez d\'abord l\'image'
            }), 400
        
        # Créer le disque
        disk_path = os.path.join(host_config['disk_dir'], f"{name}.qcow2")
        subprocess.run([
            'qemu-img', 'create', '-f', 'qcow2',
            '-F', 'qcow2', '-b', base_image,
            disk_path, f"{disk}G"
        ], check=True)
        print(f"✓ Disque: {disk_path}")
        
        # Réseau par défaut
        network_name = 'default'
        
        # Cloud-init
        seed_iso = create_cloud_init_iso(name, name, user, password, sshkey, host_config)
        print(f"✓ Cloud-init: {seed_iso}")
        
        # Créer la VM
        cmd = [
            'virt-install',
            '--connect', host_config['uri'],
            '--name', name,
            '--vcpus', str(cpu),
            '--memory', str(ram),
            f'--disk=path={disk_path},format=qcow2,bus=virtio',
            f'--disk=path={seed_iso},device=cdrom',
            '--network', f'network={network_name},model=virtio',
            '--os-variant', 'ubuntu22.04',
            '--graphics', 'none',
            '--noautoconsole',
            '--import'
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"❌ Erreur: {result.stderr}")
            conn.close()
            return jsonify({'error': result.stderr}), 500
        
        print(f"✓ VM {name} créée")
        
        # Attendre l'IP
        time.sleep(10)
        dom = conn.lookupByName(name)
        ip = _get_vm_ip(dom)
        for _ in range(30):
            if ip:
                break
            time.sleep(2)
            ip = _get_vm_ip(dom)
        
        conn.close()
        
        print(f"✓ IP: {ip or 'En attente...'}")
        print(f"{'='*50}\n")
        
        return jsonify({
            'name': name,
            'host_id': host_id,
            'ip': ip,
            'status': 'running'
        }), 201
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/vms/<n>/stop', methods=['POST'])
@require_auth
def stop_vm(name):
    vm_repo = VMRepository(g.db_session)
    vm = vm_repo.find_by_name(name)
    
    if not vm or vm.user_id != g.user_id:
        return jsonify({'error': 'VM non trouvée'}), 404
    
    try:
        conn, _ = get_connection(vm.host_id)
        dom = conn.lookupByName(name)
        if dom.isActive():
            dom.shutdown()
        conn.close()
        vm_repo.update_status(vm.id, 'stopped')
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# Route admin pour voir toutes les VMs (DB + libvirt)
@app.route('/admin/vms/all', methods=['GET'])
@require_auth
def admin_list_all_vms():
    """Route admin pour voir TOUTES les VMs (DB + libvirt)"""
    if g.username != 'admin':
        return jsonify({'error': 'Accès réservé aux administrateurs'}), 403
    
    from models import VM as VMModel
    
    all_vms = []
    
    # VMs de la base de données
    db_vms = g.db_session.query(VMModel).all()
    db_vm_names = {vm.name for vm in db_vms}
    
    # Ajouter les VMs de la DB
    for vm in db_vms:
        vm_dict = vm.to_dict()
        vm_dict['source'] = 'database'
        vm_dict['legacy'] = False
        all_vms.append(vm_dict)
    
    # Vérifier les VMs dans libvirt
    for host_id in KVM_HOSTS:
        try:
            conn, _ = get_connection(host_id)
            for dom in conn.listAllDomains():
                vm_name = dom.name()
                
                # Si pas dans la DB, c'est une VM legacy
                if vm_name not in db_vm_names:
                    info = dom.info()
                    all_vms.append({
                        'id': None,
                        'user_id': None,
                        'name': vm_name,
                        'host_id': host_id,
                        'flavor': 'unknown',
                        'image': 'unknown',
                        'status': 'running' if info[0] == 1 else 'stopped',
                        'ip_address': _get_vm_ip(dom),
                        'vcpu': info[3],
                        'ram_mb': info[2] // 1024,
                        'source': 'libvirt-only',
                        'legacy': True
                    })
            conn.close()
        except Exception as e:
            print(f"Erreur lecture hôte {host_id}: {e}")
            continue
    
    return jsonify({
        'total': len(all_vms),
        'in_database': len(db_vms),
        'legacy': len(all_vms) - len(db_vms),
        'vms': all_vms
    })

@app.route('/billing')
@require_auth
def get_billing():
    billing_repo = BillingRepository(g.db_session)
    bills = billing_repo.find_by_user(g.user_id)
    total = billing_repo.get_total_by_user(g.user_id)
    
    return jsonify({
        'bills': [b.to_dict() for b in bills],
        'total': round(total, 2)
    })

# Route metrics (pour compatibilité avec l'ancien frontend)
@app.route('/metrics')
def get_metrics():
    """Retourne les métriques des VMs actives (CPU, RAM, Disque)"""
    try:
        all_metrics = []
        
        for host_id in KVM_HOSTS:
            try:
                conn, _ = get_connection(host_id)
                for dom in conn.listAllDomains():
                    if dom.isActive():
                        try:
                            metrics = _vm_metrics(dom)
                            all_metrics.append({
                                'name': dom.name(),
                                'host': host_id,
                                **metrics
                            })
                        except:
                            continue
                conn.close()
            except:
                continue
        
        return jsonify(all_metrics)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

def _vm_metrics(dom):
    """Calcule les métriques d'une VM"""
    try:
        info = dom.info()
        cpu_count = info[3]
        mem_max = info[2]
        
        cpu_percent = 0
        try:
            t1 = dom.getCPUStats(True, 0)
            time.sleep(0.5)
            t2 = dom.getCPUStats(True, 0)
            if t1 and t2:
                cpu_time_diff = sum(s['cpu_time'] - t1[i]['cpu_time'] for i, s in enumerate(t2))
                cpu_percent = round(100 * cpu_time_diff / (cpu_count * 5e8), 1)
        except:
            pass
        
        ram_percent = 0
        try:
            mem_stats = dom.memoryStats()
            mem_used = mem_stats.get('rss', 0)
            ram_percent = round(100 * mem_used / mem_max, 1) if mem_max else 0
        except:
            pass
        
        disk_GB = 0
        try:
            xml = dom.XMLDesc(0)
            root = ET.fromstring(xml)
            for elem in root.findall(".//disk[@type='file']/source[@file]"):
                disk_path = elem.get('file')
                if disk_path and os.path.isfile(disk_path) and os.access(disk_path, os.R_OK):
                    out = subprocess.check_output(
                        ['qemu-img', 'info', '--force-share', '--output=json', disk_path],
                        stderr=subprocess.DEVNULL, timeout=2
                    )
                    disk_info = json.loads(out)
                    disk_GB = round(disk_info.get('virtual-size', 0) / 1e9, 1)
                    break
        except:
            pass
        
        return {'cpu': cpu_percent, 'ram': ram_percent, 'disk_GB': disk_GB}
    except:
        return {'cpu': 0, 'ram': 0, 'disk_GB': 0}

if __name__ == '__main__':
    print("=" * 60)
    print("IaaS Multi-tenant v2.0 avec SQLAlchemy ORM")
    print("=" * 60)
    
    # Initialiser la base de données
    db.create_tables()
    seed_database(db)
    
    print(f"✓ {len(FLAVORS)} flavors disponibles")
    print(f"✓ {len(KVM_HOSTS)} hôtes KVM configurés")
    print("=" * 60)
    print("\nCompte par défaut:")
    print("  Username: admin")
    print("  Password: admin123")
    print("\n🌐 API: http://localhost:5000")
    print("=" * 60)
    app.run(host='0.0.0.0', port=5000, debug=True)