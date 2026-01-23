// user-app.js - Logique de l'interface utilisateur

let selectedFlavor = 'M';
let vmToDelete = null;

// Initialisation
(async function init() {
    const user = await checkAuth();
    if (!user) return;

    // Rediriger admin vers admin.html
    if (user.is_admin) {
        window.location.href = 'admin.html';
        return;
    }

    document.getElementById('username').textContent = user.username;

    loadData();
    setInterval(loadVMs, 10000);
})();

function loadData() {
    loadVMs();
    loadBilling();
}

// Navigation
function showTab(tab) {
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.section').forEach(s => s.classList.remove('active'));
    event.target.classList.add('active');
    document.getElementById(`${tab}Section`).classList.add('active');

    if (tab === 'billing') loadBilling();
    else if (tab === 'images') loadImages();
}

// Gestion du modal
function openModal() {
    document.getElementById('modal').classList.add('show');
    loadFlavorsInModal();
    loadImagesInModal();
}

function closeModal() {
    document.getElementById('modal').classList.remove('show');
}

window.onclick = (e) => {
    if (e.target.id === 'modal') closeModal();
    if (e.target.id === 'confirmModal') closeConfirmModal();
};

// Flavors
async function loadFlavorsInModal() {
    const flavors = await loadFlavors();
    const container = document.getElementById('flavorsList');
    container.innerHTML = flavors.map(f => `
        <div class="flavor-card ${f.id === selectedFlavor ? 'selected' : ''}" 
             onclick="selectFlavor('${f.id}')">
            <h3>${f.name}</h3>
            <div class="flavor-specs">
                <span>🖥️ ${f.vcpu} vCPU</span>
                <span>💾 ${f.ram_mb / 1024} GB RAM</span>
                <span>💿 ${f.disk_gb} GB Disque</span>
            </div>
            <div class="flavor-price">${f.price_month} FCFA/mois</div>
        </div>
    `).join('');
}

function selectFlavor(id) {
    selectedFlavor = id;
    document.querySelectorAll('.flavor-card').forEach(c => c.classList.remove('selected'));
    event.target.closest('.flavor-card').classList.add('selected');
}

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
                        ${img.downloaded ? `Taille: ${img.size_mb} MB<br>Prête à l'emploi` : 'Contactez l\'administrateur'}
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
            tbody.innerHTML = `<tr><td colspan="6" style="text-align: center; padding: 2rem; color: var(--muted);">Aucune instance créée</td></tr>`;
            document.getElementById('statTotal').textContent = '0';
            document.getElementById('statRunning').textContent = '0';
            return;
        }
        
        tbody.innerHTML = vms.map(vm => {
            let ipDisplay = '-';
            if (vm.ip_address) {
                ipDisplay = `<div style="display: flex; align-items: center; gap: 0.5rem;"><span>${vm.ip_address}</span><button class="btn btn-success" onclick="testSSH('${vm.ip_address}', '${vm.name}')" style="padding: 0.25rem 0.5rem; font-size: 0.75rem;" title="Tester SSH">🔌 SSH</button></div>`;
            } else if (vm.status === 'running') {
                ipDisplay = '<span style="color: var(--warning);">⏳ En attente...</span>';
            }
            
            return `
                <tr>
                    <td><strong>${vm.name}</strong></td>
                    <td><span class="badge">${vm.flavor}</span></td>
                    <td>${vm.image}</td>
                    <td><span class="status ${vm.status}">${vm.status}</span></td>
                    <td>${ipDisplay}</td>
                    <td>
                        <div class="vm-actions">
                            <button class="btn btn-success" onclick="startVM('${vm.name}')" title="Démarrer">▶</button>
                            <button class="btn btn-warning" onclick="stopVM('${vm.name}')" title="Arrêter">⏸</button>
                            <button class="btn btn-danger" onclick="openConfirmModal('${vm.name}')" title="Supprimer">🗑️</button>
                        </div>
                    </td>
                </tr>
            `;
        }).join('');
        
        document.getElementById('statTotal').textContent = vms.length;
        document.getElementById('statRunning').textContent = vms.filter(v => v.status === 'running').length;
    } catch (e) {
        console.error('Erreur VMs:', e);
        document.getElementById('vmsList').innerHTML = `<tr><td colspan="6" style="text-align: center; padding: 2rem; color: var(--ko);">Erreur de chargement</td></tr>`;
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
        showToast(`Instance ${name} démarrée`, 'success');
        setTimeout(loadVMs, 1000);
    } catch (e) {
        showToast('Erreur lors du démarrage', 'error');
    }
}

async function stopVM(name) {
    try {
        await apiRequest(`/vms/${name}/stop`, { method: 'POST' });
        showToast(`Instance ${name} arrêtée`, 'success');
        setTimeout(loadVMs, 1000);
    } catch (e) {
        showToast('Erreur lors de l\'arrêt', 'error');
    }
}

function openConfirmModal(vmName) {
    vmToDelete = vmName;
    document.getElementById('vmToDelete').textContent = vmName;
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
            showToast(`Instance ${vmToDelete} supprimée avec succès`, 'success');
            closeConfirmModal();
            setTimeout(() => {
                loadVMs();
                loadBilling();
            }, 1000);
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
        flavor: selectedFlavor,
        image: formData.get('image'),
        user: formData.get('user'),
        password: formData.get('password'),
        sshkey: formData.get('sshkey') || ''
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
            
            loadBilling();
            e.target.reset();
        } else {
            showToast(result.error || 'Erreur lors de la création', 'error');
        }
    } catch (e) {
        showToast('Erreur: ' + e.message, 'error');
    }
});

// Facturation
async function loadBilling() {
    try {
        const response = await apiRequest('/billing');
        const data = await response.json();
        const tbody = document.getElementById('billingList');
        
        if (data.bills.length === 0) {
            tbody.innerHTML = `<tr><td colspan="3" style="text-align: center; padding: 2rem; color: var(--muted);">Aucune facturation</td></tr>`;
            document.getElementById('totalBilling').textContent = '0';
        } else {
            tbody.innerHTML = data.bills.map(b => `
                <tr>
                    <td>${new Date(b.created_at).toLocaleString('fr-FR')}</td>
                    <td>${b.description}</td>
                    <td><strong>${b.amount.toFixed(2)} FCFA</strong></td>
                </tr>
            `).join('');
            document.getElementById('totalBilling').textContent = data.total.toFixed(2);
        }
    } catch (e) {
        console.error('Erreur billing:', e);
    }
}