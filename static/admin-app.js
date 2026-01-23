// admin-app.js - Logique de l'interface administrateur

let vmToDelete = null;

// Initialisation
(async function init() {
    const user = await checkAuth();
    if (!user) return;

    // Rediriger non-admin vers user.html
    if (!user.is_admin) {
        window.location.href = 'user.html';
        return;
    }

    document.getElementById('username').textContent = user.username;

    loadData();
    setInterval(loadVMs, 10000);
})();

function loadData() {
    loadVMs();
    loadUsers();
}

// Navigation
function showTab(tab) {
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.section').forEach(s => s.classList.remove('active'));
    event.target.classList.add('active');
    document.getElementById(`${tab}Section`).classList.add('active');

    if (tab === 'users') loadUsers();
    else if (tab === 'images') loadImages();
    else if (tab === 'hosts') loadHosts();
}

async function loadHostsInModal() {
    try {
        const response = await apiRequest('/hosts/status');
        const hosts = await response.json();
        const select = document.getElementById('hostSelect');

        if (!select) {
            console.error('Element #hostSelect non trouvé');
            return;
        }

        // Filtrer uniquement les hôtes en ligne
        const onlineHosts = hosts.filter(h => h.status === 'online');

        if (onlineHosts.length === 0) {
            select.innerHTML = '<option value="">Aucun hôte disponible</option>';
            showToast('Aucun hôte KVM disponible', 'error');
            return;
        }

        // Générer les options
        select.innerHTML = onlineHosts.map(host => {
            const resourcesInfo = host.resources ?
                `(${host.resources.vcpu.available}/${host.resources.vcpu.total} vCPU, ${host.resources.ram_mb.available}/${host.resources.ram_mb.total} MB RAM)` :
                '';

            return `<option value="${host.id}">${host.name} ${resourcesInfo}</option>`;
        }).join('');

        console.log(`✅ ${onlineHosts.length} hôte(s) chargé(s)`);

    } catch (e) {
        console.error('Erreur chargement hôtes:', e);
    }
}

// Gestion des modals
function openModal() {
    document.getElementById('modal').classList.add('show');
    loadImagesInModal();
    loadHostsInModal();
}

function closeModal() {
    document.getElementById('modal').classList.remove('show');
}

function openCreateUserModal() {
    document.getElementById('createUserModal').classList.add('show');
}

function closeCreateUserModal() {
    document.getElementById('createUserModal').classList.remove('show');
}

window.onclick = (e) => {
    if (e.target.id === 'modal') closeModal();
    if (e.target.id === 'confirmModal') closeConfirmModal();
    if (e.target.id === 'createUserModal') closeCreateUserModal();
};

// Images
async function loadImagesInModal() {
    const images = await loadAvailableImages();
    const select = document.getElementById('imageSelect');

    if (!images || images.length === 0) {
        select.innerHTML = '<option value="">Aucune image disponible</option>';
        showToast('Aucune image disponible. Vérifiez ~/Codes/base-images/', 'warning');
    } else {
        select.innerHTML = images.map(img =>
            `<option value="${img.name}">${img.name} (${img.size_mb} MB)</option>`
        ).join('');
    }
}

async function loadImages() {
    try {
        const response = await fetch(`${API_URL}/images`);
        const images = await response.json();
        const container = document.getElementById('imagesList');

        if (!images || images.length === 0) {
            container.innerHTML = '<div style="grid-column: 1/-1; text-align: center; padding: 2rem; color: var(--muted);">Aucune image configurée</div>';
        } else {
            container.innerHTML = images.map(img => `
                <div style="background: var(--card); border: 1px solid var(--border); border-radius: 12px; padding: 1.5rem;">
                    <span style="display: inline-block; padding: 0.25rem 0.75rem; border-radius: 12px; font-size: 0.75rem; font-weight: 600; margin-bottom: 0.5rem; ${img.downloaded ? 'background: rgba(16, 185, 129, 0.2); color: var(--ok);' : 'background: rgba(239, 68, 68, 0.2); color: var(--ko);'}">
                        ${img.downloaded ? '✓ Disponible' : '✗ Non téléchargée'}
                    </span>
                    <h3 style="color: var(--accent); margin-bottom: 0.5rem;">${img.name}</h3>
                    <div style="color: var(--muted); font-size: 0.875rem; margin-top: 0.5rem;">
                        ${img.downloaded ? `Taille: ${img.size_mb} MB<br>Prête à l'emploi` : 'Exécutez: ./download-images.sh'}
                    </div>
                </div>
            `).join('');
        }
    } catch (e) {
        console.error('Erreur images:', e);
    }
}

// VMs
async function loadVMs() {
    try {
        const response = await apiRequest('/vms');
        const vms = await response.json();
        const tbody = document.getElementById('vmsList');
        
        if (vms.length === 0) {
            tbody.innerHTML = `<tr><td colspan="7" style="text-align: center; padding: 2rem; color: var(--muted);">Aucune instance créée</td></tr>`;
            document.getElementById('statTotal').textContent = '0';
            document.getElementById('statRunning').textContent = '0';
            return;
        }
        
        tbody.innerHTML = vms.map(vm => {
            // ✅ CORRECTION : Utiliser display_name au lieu de name
            const displayName = vm.display_name ;
            const technicalName = vm.name;
            
            let ipDisplay = '-';
            if (vm.ip_address) {
                // ✅ Utiliser technicalName pour les actions (API)
                ipDisplay = `<div style="display: flex; align-items: center; gap: 0.5rem;"><span>${vm.ip_address}</span><button class="btn btn-success" onclick="testSSH('${vm.ip_address}', '${technicalName}')" style="padding: 0.25rem 0.5rem; font-size: 0.75rem;" title="Tester SSH">🔌 SSH</button></div>`;
            } else if (vm.status === 'running') {
                ipDisplay = '<span style="color: var(--warning);">⏳ En attente...</span>';
            }
            
            const flavorDisplay = vm.flavor === 'admin-custom' 
                ? `<span style="color: var(--ko); font-weight: 600;">ADMIN</span> ${vm.vcpu || '?'} vCPU, ${(vm.ram_mb || 0) / 1024} GB`
                : `<span class="badge">${vm.flavor}</span>`;
            
            return `
                <tr>
                    <td>
                        <strong>${displayName}</strong>
                    </td>
                    <td>${flavorDisplay}</td>
                    <td>${vm.image}</td>
                    <td>${vm.host_id}</td>
                    <td><span class="status ${vm.status}">${vm.status}</span></td>
                    <td>${ipDisplay}</td>
                    <td>
                        <div class="vm-actions">
                            <button class="btn btn-success" onclick="startVM('${technicalName}')" title="Démarrer">▶</button>
                            <button class="btn btn-warning" onclick="stopVM('${technicalName}')" title="Arrêter">⏸</button>
                            <button class="btn btn-danger" onclick="openConfirmModal('${technicalName}', '${displayName}')" title="Supprimer">🗑️</button>
                        </div>
                    </td>
                </tr>
            `;
        }).join('');
        
        document.getElementById('statTotal').textContent = vms.length;
        document.getElementById('statRunning').textContent = vms.filter(v => v.status === 'running').length;
    } catch (e) {
        console.error('Erreur VMs:', e);
        document.getElementById('vmsList').innerHTML = `<tr><td colspan="7" style="text-align: center; padding: 2rem; color: var(--ko);">Erreur de chargement</td></tr>`;
    }
}

async function testSSH(ip, vmName) {
    showToast(`Test de connexion SSH vers ${ip}...`, 'warning');
    try {
        const response = await apiRequest(`/vms/${vmName}/test-ssh`, { method: 'POST' });
        const result = await response.json();
        if (response.ok && result.success) {
            showToast(`✅ SSH accessible sur ${ip}:22`, 'success');
        } else {
            showToast(`❌ SSH non accessible: ${result.error || 'Port 22 fermé'}`, 'error');
        }
    } catch (e) {
        showToast(`❌ Erreur test SSH: ${e.message}`, 'error');
    }
}

async function startVM(name) {
    try {
        await apiRequest(`/vms/${name}/start`, { method: 'POST' });
        showToast(`Instance démarrée`, 'success');
        setTimeout(loadVMs, 1000);
    } catch (e) {
        showToast('Erreur lors du démarrage', 'error');
    }
}

async function stopVM(name) {
    try {
        await apiRequest(`/vms/${name}/stop`, { method: 'POST' });
        showToast(`Instance arrêtée`, 'success');
        setTimeout(loadVMs, 1000);
    } catch (e) {
        showToast('Erreur lors de l\'arrêt', 'error');
    }
}

// ✅ CORRECTION : Accepter displayName en paramètre
function openConfirmModal(technicalName, displayName) {
    vmToDelete = technicalName;
    document.getElementById('vmToDelete').textContent = displayName || technicalName;
    document.getElementById('confirmModal').classList.add('show');
}

function closeConfirmModal() {
    vmToDelete = null;
    document.getElementById('confirmModal').classList.remove('show');
}

async function confirmDelete() {
    if (!vmToDelete) return;
    try {
        const response = await apiRequest(`/vms/${vmToDelete}`, { method: 'DELETE' });
        if (response.ok) {
            showToast(`Instance supprimée avec succès`, 'success');
            closeConfirmModal();
            setTimeout(loadVMs, 1000);
        } else {
            const result = await response.json();
            showToast(result.error || 'Erreur lors de la suppression', 'error');
        }
    } catch (e) {
        showToast('Erreur: ' + e.message, 'error');
    }
}

// Formulaire création VM
document.getElementById('deployForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    const formData = new FormData(e.target);
    const data = {
        name: formData.get('name'),
        cpu: parseInt(formData.get('cpu')),
        ram: parseInt(formData.get('ram')),
        disk: parseInt(formData.get('disk')),
        image: formData.get('image'),
        user: formData.get('user'),
        password: formData.get('password'),
        sshkey: formData.get('sshkey') || '',
        host: formData.get('host') || 'local'
    };
    
    closeModal();
    showToast(`Création de ${data.name} en cours...`, 'warning');
    
    try {
        const response = await apiRequest('/vms', { method: 'POST', body: JSON.stringify(data) });
        const result = await response.json();
        
        if (response.ok) {
            showToast(`Instance ${data.name} créée avec succès !`, 'success');
            loadVMs();
            
            let refreshCount = 0;
            const refreshInterval = setInterval(() => {
                loadVMs();
                refreshCount++;
                if (refreshCount >= 15) clearInterval(refreshInterval);
            }, 2000);
            
            e.target.reset();
        } else {
            showToast(result.error || 'Erreur lors de la création', 'error');
        }
    } catch (e) {
        showToast('Erreur: ' + e.message, 'error');
    }
});

// Gestion des utilisateurs
async function loadUsers() {
    try {
        const response = await apiRequest('/admin/users');
        const users = await response.json();
        const tbody = document.getElementById('usersList');
        
        tbody.innerHTML = users.map(user => `
            <tr>
                <td>${user.id}</td>
                <td>
                    <strong>${user.username}</strong>
                    ${user.is_admin ? '<span class="admin-badge" style="margin-left: 0.5rem;">ADMIN</span>' : ''}
                </td>
                <td>${user.email || '-'}</td>
                <td>${user.vm_count}</td>
                <td>${user.total_billing} FCFA</td>
                <td>${new Date(user.created_at).toLocaleDateString('fr-FR')}</td>
                <td>
                    <div class="vm-actions">
                        ${!user.is_admin ? `
                            <button class="btn btn-warning" onclick="resetUserPassword(${user.id}, '${user.username}')" title="Réinitialiser mot de passe">
                                🔑
                            </button>
                            <button class="btn btn-danger" onclick="deleteUser(${user.id}, '${user.username}')" title="Supprimer">
                                🗑️
                            </button>
                        ` : '<span style="color: var(--muted);">-</span>'}
                    </div>
                </td>
            </tr>
        `).join('');
    } catch (e) {
        console.error('Erreur users:', e);
    }
}

document.getElementById('createUserForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    const data = Object.fromEntries(new FormData(e.target));
    
    try {
        const response = await apiRequest('/admin/users', {
            method: 'POST',
            body: JSON.stringify(data)
        });
        
        if (response.ok) {
            showToast('Utilisateur créé avec succès', 'success');
            closeCreateUserModal();
            loadUsers();
            e.target.reset();
        } else {
            const result = await response.json();
            showToast(result.error, 'error');
        }
    } catch (e) {
        showToast('Erreur lors de la création', 'error');
    }
});

async function deleteUser(userId, username) {
    if (!confirm(`Supprimer l'utilisateur ${username} et toutes ses VMs ?`)) {
        return;
    }
    
    try {
        const response = await apiRequest(`/admin/users/${userId}`, {
            method: 'DELETE'
        });
        
        if (response.ok) {
            showToast(`Utilisateur ${username} supprimé`, 'success');
            loadUsers();
        } else {
            const result = await response.json();
            showToast(result.error, 'error');
        }
    } catch (e) {
        showToast('Erreur lors de la suppression', 'error');
    }
}

async function resetUserPassword(userId, username) {
    const newPassword = prompt(`Nouveau mot de passe pour ${username}:`);
    if (!newPassword || newPassword.length < 6) {
        showToast('Mot de passe trop court (min 6 caractères)', 'error');
        return;
    }
    
    try {
        const response = await apiRequest(`/admin/users/${userId}/reset-password`, {
            method: 'POST',
            body: JSON.stringify({ password: newPassword })
        });
        
        if (response.ok) {
            showToast(`Mot de passe de ${username} réinitialisé`, 'success');
        } else {
            const result = await response.json();
            showToast(result.error, 'error');
        }
    } catch (e) {
        showToast('Erreur lors de la réinitialisation', 'error');
    }
}

// Gestion des hôtes
async function loadHosts() {
    try {
        const response = await apiRequest('/hosts/status');
        const hosts = await response.json();
        const container = document.getElementById('hostsList');
        
        container.innerHTML = hosts.map(host => {
            const isOnline = host.status === 'online';
            return `
                <div style="background: var(--card); border: 1px solid var(--border); border-radius: 12px; padding: 1.5rem; margin-bottom: 1rem;">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 1rem;">
                        <h3 style="color: var(--accent);">${host.name}</h3>
                        <span style="display: inline-block; padding: 0.25rem 0.75rem; border-radius: 12px; font-size: 0.75rem; font-weight: 600; ${isOnline ? 'background: rgba(16, 185, 129, 0.2); color: var(--ok);' : 'background: rgba(239, 68, 68, 0.2); color: var(--ko);'}">
                            ${isOnline ? '✓ En ligne' : '✗ Hors ligne'}
                        </span>
                    </div>
                    <div style="color: var(--muted); font-size: 0.875rem;">
                        <div>URI: <code style="background: var(--bg); padding: 0.25rem 0.5rem; border-radius: 4px;">${host.uri}</code></div>
                        ${isOnline ? `
                            <div style="margin-top: 0.5rem;">
                                VMs: ${host.vms_running}/${host.vms_total} actives<br>
                                CPU: ${host.resources.vcpu.used}/${host.resources.vcpu.total} vCPU<br>
                                RAM: ${host.resources.ram_mb.used}/${host.resources.ram_mb.total} MB
                            </div>
                        ` : `<div style="margin-top: 0.5rem; color: var(--ko);">Erreur: ${host.error}</div>`}
                    </div>
                </div>
            `;
        }).join('');
    } catch (e) {
        console.error('Erreur hosts:', e);
    }
}