#!/usr/bin/env python3
import os
import tempfile
import subprocess
import libvirt
import time
import json
import glob
import xml.etree.ElementTree as ET
from flask import Flask, request, jsonify

app = Flask(__name__)
app = Flask(__name__, static_folder='./templates')

# --- CONFIGURATION ---
URI = 'qemu:///system'
CONN = libvirt.open(URI)

ISO_DIR = os.path.expanduser('~/Codes/iso')
DISK_DIR = os.path.expanduser('~/.local/share/libvirt/images')
BASE_ISO_DIR = os.path.expanduser('~/.local/share/libvirt/images/base')

ISO_MAPPING = {
    'ubuntu': 'ubuntu-24.04.3-live-server-amd64.iso',
    'fedora': 'fedora-server-xx.iso',  
}
os.makedirs(DISK_DIR, exist_ok=True)

# -------------------------------------------------
# Cloud-init ISO (Ubuntu)
# -------------------------------------------------
def _make_cloudinit_iso(tmpd, hostname, user, passwd, sshkey):
    """Crée un ISO cloud-init pour Ubuntu avec autoinstall"""
    # Hasher le mot de passe
    import secrets
    salt = secrets.token_hex(8)
    passwd_hash = subprocess.check_output(
        ['openssl', 'passwd', '-6', '-salt', salt, passwd],
        text=True
    ).strip()
    
    # Bloc SSH
    ssh_block = ""
    if sshkey:
        ssh_block = f'\n    ssh_authorized_keys:\n      - "{sshkey}"'
    
    user_data = f"""#cloud-config
autoinstall:
  version: 1
  locale: fr_FR.UTF-8
  keyboard:
    layout: fr
  identity:
    hostname: {hostname}
    username: {user}
    password: "{passwd_hash}"
  ssh:
    install-server: true
    allow-pw: true
  storage:
    layout:
      name: direct
  packages:
    - qemu-guest-agent
    - openssh-server
  late-commands:
    - echo '{user} ALL=(ALL) NOPASSWD:ALL' > /target/etc/sudoers.d/{user}
"""
    
    if sshkey:
        user_data += f"""    - mkdir -p /target/home/{user}/.ssh
    - echo "{sshkey}" > /target/home/{user}/.ssh/authorized_keys
    - chown -R {user}:{user} /target/home/{user}/.ssh
    - chmod 700 /target/home/{user}/.ssh
    - chmod 600 /target/home/{user}/.ssh/authorized_keys
"""
    
    # Écrire les fichiers
    with open(os.path.join(tmpd, 'user-data'), 'w') as f:
        f.write(user_data)
    
    with open(os.path.join(tmpd, 'meta-data'), 'w') as f:
        f.write(f'instance-id: {hostname}\nlocal-hostname: {hostname}\n')
    
    # Créer l'ISO
    cidata = os.path.join(tmpd, 'cidata.iso')
    subprocess.run([
        'genisoimage', '-quiet', '-output', cidata, '-volid', 'cidata',
        '-joliet', '-rock',
        os.path.join(tmpd, 'user-data'),
        os.path.join(tmpd, 'meta-data')
    ], check=True)
    
    return cidata

# -------------------------------------------------
# Métriques CPU / RAM / Disque
# -------------------------------------------------
def _vm_metrics(dom):
    try:
        info = dom.info()
        cpu_count = info[3]
        mem_max = info[2]  # KiB
        
        # CPU %
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
        
        # RAM %
        ram_percent = 0
        try:
            mem_stats = dom.memoryStats()
            mem_used = mem_stats.get('rss', 0)  # KiB
            ram_percent = round(100 * mem_used / mem_max, 1) if mem_max else 0
        except:
            pass
        
        # Disque - Ne pas bloquer si erreur
        disk_GB = 0
        try:
            xml = dom.XMLDesc(0)
            root = ET.fromstring(xml)
            disk_path = None
            for elem in root.findall(".//disk[@type='file']/source[@file]"):
                disk_path = elem.get('file')
                break
            
            if disk_path and os.path.isfile(disk_path):
                # Vérifier les permissions avant de lire
                if os.access(disk_path, os.R_OK):
                    out = subprocess.check_output(
                        ['qemu-img', 'info', '--force-share', '--output=json', disk_path],
                        stderr=subprocess.DEVNULL,
                        timeout=2
                    )
                    disk_info = json.loads(out)
                    virt_size = disk_info.get('virtual-size', 0)
                    disk_GB = round(virt_size / 1e9, 1)
        except:
            pass  # Ignorer silencieusement les erreurs de disque
        
        return {'cpu': cpu_percent, 'ram': ram_percent, 'disk_GB': disk_GB}
    except Exception as e:
        # Retourner des valeurs par défaut en cas d'erreur
        return {'cpu': 0, 'ram': 0, 'disk_GB': 0}

def get_iso_path(distro_name):
    """
    Récupère le chemin complet de l'ISO depuis le répertoire de base
    """
    distro_key = distro_name.lower().split('_')[0]  # ubuntu_vm_test1 -> ubuntu
    
    if distro_key not in ISO_MAPPING:
        raise ValueError(f"Distribution '{distro_key}' non supportée. Distributions disponibles: {list(ISO_MAPPING.keys())}")
    
    iso_filename = ISO_MAPPING[distro_key]
    iso_path = os.path.join(BASE_ISO_DIR, iso_filename)
    
    # Vérifier que l'ISO existe
    if not os.path.exists(iso_path):
        raise FileNotFoundError(f"ISO non trouvée: {iso_path}")
    
    return iso_path

# -------------------------------------------------
# Attendre l'IP
# -------------------------------------------------
def _wait_ip(dom, timeout=120):
    """Attend que la VM obtienne une IP"""
    for _ in range(timeout):
        time.sleep(1)
        if dom.isActive():
            try:
                ifaces = dom.interfaceAddresses(libvirt.VIR_DOMAIN_INTERFACE_ADDRESSES_SRC_LEASE)
                for iface_data in ifaces.values():
                    for addr in iface_data.get('addrs', []):
                        if addr['type'] == libvirt.VIR_IP_ADDR_TYPE_IPV4:
                            return addr['addr']
            except:
                pass
    return None

def deploy(vm_config):
    vm_name = vm_config['name']
    distro = vm_config.get('distro', 'ubuntu')  
    
    print(f"==================================================")
    print(f"Déploiement de {vm_name}")
    print(f"==================================================")
    
    try:
        # Récupérer l'ISO depuis le répertoire de base
        iso_path = get_iso_path(distro)
        print(f"ISO: {os.path.basename(iso_path)} (depuis {BASE_ISO_DIR})")
        
        cidata_dest = os.path.join(
            os.path.expanduser('~/.local/share/libvirt/images'),
            f'{vm_name}-cidata.iso'
        )
        
        # Utiliser shutil au lieu de subprocess
        import shutil
        shutil.copy2(cidata_iso, cidata_dest)
        print(f"✓ Cloud-init ISO: {cidata_dest}")
        
        #
        virt_install_cmd = [
            'virt-install',
            '--name', vm_name,
            '--ram', str(vm_config.get('ram', 2048)),
            '--vcpus', str(vm_config.get('cpu', 2)),
            '--disk', f"path={disk_path},size={vm_config.get('disk', 20)}",
            '--cdrom', iso_path,  # Utiliser l'ISO du répertoire de base
            '--disk', f"path={cidata_dest},device=cdrom",
            '--os-variant', get_os_variant(distro),
            '--network', 'network=default',
            '--console', 'pty,target_type=serial',
            
        ]
        
        subprocess.run(virt_install_cmd, check=True)
        print(f"✓ VM {vm_name} déployée avec succès")
        
    except FileNotFoundError as e:
        print(f"❌ Erreur: {e}")
        print(f"💡 Vérifiez que les ISOs sont dans: {BASE_ISO_DIR}")
        raise
    except Exception as e:
        print(f"❌ Erreur: {e}")
        raise


def get_os_variant(distro):
    """
    Retourne le variant OS pour virt-install
    """
    variants = {
        'ubuntu': 'ubuntu24.04',
        'fedora': 'fedora39',  
    }
    distro_key = distro.lower().split('_')[0]
    return variants.get(distro_key, 'linux2022')
# -------------------------------------------------
# Routes
# -------------------------------------------------
@app.route('/')
def index():
    try:
        with open('./templates/index.html', 'r') as f:
            return f.read()
    except FileNotFoundError:
        return "<h1>Erreur: index.html non trouvé</h1>", 404

@app.route('/isos')
def isos():
    try:
        files = glob.glob(os.path.join(ISO_DIR, '*.iso'))
        return jsonify([os.path.basename(f) for f in files])
    except:
        return jsonify([])

@app.route('/vms')
def vms():
    lst = []
    try:
        for dom in CONN.listAllDomains():
            try:
                info = dom.info()
                
                # Récupérer l'IP si la VM est active
                ip = ''
                if info[0] == 1:  # Running
                    try:
                        ifaces = dom.interfaceAddresses(libvirt.VIR_DOMAIN_INTERFACE_ADDRESSES_SRC_LEASE)
                        for iface_data in ifaces.values():
                            for addr in iface_data.get('addrs', []):
                                if addr['type'] == libvirt.VIR_IP_ADDR_TYPE_IPV4:
                                    ip = addr['addr']
                                    break
                    except:
                        pass
                
                lst.append({
                    'name': dom.name(),
                    'state': info[0],  # 0=stopped, 1=running
                    'cpu': info[3],
                    'ram': info[2] // 1024,  # Mo
                    'ip': ip
                })
            except:
                continue
    except Exception as e:
        print(f"Erreur liste VMs: {e}")
    
    return jsonify(lst)

@app.route('/metrics')
def metrics():
    lst = []
    try:
        for dom in CONN.listAllDomains():
            if dom.isActive():
                try:
                    lst.append({'name': dom.name(), **_vm_metrics(dom)})
                except:
                    continue
    except Exception as e:
        print(f"Erreur metrics: {e}")
    
    return jsonify(lst)

@app.route('/start', methods=['POST'])
def start():
    try:
        name = request.json['name']
        dom = CONN.lookupByName(name)
        if not dom.isActive():
            dom.create()
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/stop', methods=['POST'])
def stop():
    try:
        name = request.json['name']
        dom = CONN.lookupByName(name)
        if dom.isActive():
            dom.shutdown()
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/delete', methods=['POST'])
def delete():
    try:
        name = request.json['name']
        dom = CONN.lookupByName(name)
        
        # Récupérer le disque avant suppression
        xml = dom.XMLDesc(0)
        root = ET.fromstring(xml)
        disk_path = None
        for elem in root.findall(".//disk[@type='file']/source[@file]"):
            disk_path = elem.get('file')
            break
        
        # Supprimer la VM
        if dom.isActive():
            dom.destroy()
        dom.undefine()
        
        # Supprimer le disque
        if disk_path and os.path.isfile(disk_path):
            os.remove(disk_path)
            print(f"✓ Disque supprimé: {disk_path}")
        
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/deploy', methods=['POST'])
def deploy():
    try:
        data = request.get_json()
        name = data['name']
        iso_basename = data['iso']
        user = data['user']
        passwd = data['password']
        sshkey = data.get('sshkey', '').strip()
        cpu = int(data['cpu'])
        ram = int(data['ram']) * 1024  # Convertir Go -> Mo
        disk = int(data['disk'])
        
        print(f"\n{'='*50}")
        print(f"Déploiement de {name}")
        print(f"{'='*50}")
        print(f"ISO: {iso_basename}")
        print(f"User: {user}")
        print(f"CPU: {cpu}, RAM: {ram}Mo, Disk: {disk}Go")
        
        # Vérifier que la VM n'existe pas déjà
        try:
            CONN.lookupByName(name)
            return jsonify({'error': 'VM existe déjà'}), 409
        except:
            pass
        
        iso_path = os.path.join(ISO_DIR, iso_basename)
        if not os.path.exists(iso_path):
            return jsonify({'error': f'ISO introuvable: {iso_basename}'}), 400
        
        # Créer le disque
        disk_path = f"{DISK_DIR}/{name}.qcow2"
        subprocess.run([
            'qemu-img', 'create', '-f', 'qcow2',
            disk_path, f"{disk}G"
        ], check=True)
        print(f"✓ Disque créé: {disk_path}")
        
        # Déploiement Ubuntu
        if 'ubuntu' in iso_basename.lower():
            os_variant = 'ubuntu24.04'
            
            # Créer cloud-init dans un dossier temporaire
            with tempfile.TemporaryDirectory() as tmpd:
                cidata_iso = _make_cloudinit_iso(tmpd, name, user, passwd, sshkey)
                
                # Copier l'ISO dans un emplacement permanent
                cidata_dest = f"{DISK_DIR}/{name}-cidata.iso"
                subprocess.run(['cp', cidata_iso, cidata_dest], check=True)
                print(f"✓ Cloud-init créé: {cidata_dest}")
                
                # Lancer virt-install
                cmd = [
                    'virt-install',
                    '--connect', URI,
                    '--name', name,
                    '--vcpus', str(cpu),
                    '--memory', str(ram),
                    f'--disk=path={disk_path},format=qcow2',
                    f'--disk=path={cidata_dest},device=cdrom',
                    '--cdrom', iso_path,
                    '--network', 'bridge=virbr0',
                    '--os-variant', os_variant,
                    
                ]
                
                print(f"Commande: {' '.join(cmd)}")
                result = subprocess.run(cmd, capture_output=True, text=True)
                
                if result.returncode != 0:
                    print(f"❌ Erreur virt-install: {result.stderr}")
                    return jsonify({'error': result.stderr}), 500
                
                print(f"✓ VM {name} créée")
        
        else:
            # Fedora ou autre
            return jsonify({'error': 'Seul Ubuntu est supporté pour le moment'}), 400
        
        # Attendre l'IP
        print("⏳ Attente de l'IP...")
        time.sleep(5)
        dom = CONN.lookupByName(name)
        ip = _wait_ip(dom, timeout=60)
        
        print(f"✓ IP: {ip or 'Installation en cours...'}")
        print(f"{'='*50}\n")
        
        return jsonify({'ip': ip or 'Installation en cours...'})
    
    except Exception as e:
        print(f"❌ Erreur: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    print("=" * 50)
    print("Mini-Cloud IaaS - Démarrage")
    print("=" * 50)
    print(f"ISO_DIR  : {ISO_DIR}")
    print(f"DISK_DIR : {DISK_DIR}")
    print(f"Connexion: {URI}")
    print("=" * 50)
    print("\n🌐 Accès: http://localhost:5000")
    print("=" * 50)
    app.run(host='0.0.0.0', port=5000, debug=True)