const STATE = ['Éteinte', 'En cours', 'Suspendue'];

function showToast(msg, type = 'success') {
    const toast = document.getElementById('toast');
    toast.textContent = msg;
    toast.className = `toast ${type} show`;
    setTimeout(() => toast.classList.remove('show'), 4000);
}

function openModal() {
    document.getElementById('modal').classList.add('show');
}

function closeModal() {
    document.getElementById('modal').classList.remove('show');
}

async function fillIsos() {
    try {
        const list = await fetch('/isos').then(r => r.json());
        const sel = document.getElementById('isoSelect');
        sel.innerHTML = '';

        if (list.length === 0) {
            sel.innerHTML = '<option value="">Aucune ISO trouvée</option>';
            return;
        }

        list.forEach(f => {
            const opt = document.createElement('option');
            opt.value = f;
            opt.textContent = f;
            sel.appendChild(opt);
        });
    } catch (e) {
        console.error('Erreur ISOs:', e);
    }
}

async function updateMon() {
    try {
        const data = await fetch('/vms').then(r => r.json());
        const tb = document.querySelector('#mon');

        if (data.length === 0) {
            tb.innerHTML = `<tr><td colspan="9">
                <div class="empty-state">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <path d="M9 3v2m6-2v2M9 19v2m6-2v2M5 9H3m2 6H3m18-6h-2m2 6h-2M7 19h10a2 2 0 002-2V7a2 2 0 00-2-2H7a2 2 0 00-2 2v10a2 2 0 002 2zM9 9h6v6H9V9z"/>
                    </svg>
                    <p>Aucune instance pour le moment</p>
                </div>
            </td></tr>`;
            return;
        }

        tb.innerHTML = data.map(v => `<tr data-vm="${v.name}">
            <td><strong>${v.name}</strong></td>
            <td><span class="status ${v.state===1?'on':'off'}">${STATE[v.state]||'Eteint'}</span></td>
            <td>${v.cpu}</td>
            <td class="ram-max">${v.ram} Mo</td>
            <td class="cpu">-</td>
            <td class="ram">-</td>
            <td class="disk">-</td>
            <td>${v.ip||'-'}</td>
            <td>
                <div class="actions">
                    <button class="btn ${v.state===1?'btn-danger':'btn-success'}" 
                            onclick="toggleVm('${v.name}',${v.state})">
                        ${v.state===1?'Stop':'Start'}
                    </button>
                    <button class="btn btn-danger" onclick="deleteVm('${v.name}')">
                        🗑
                    </button>
                </div>
            </td>
        </tr>`).join('');
    } catch (e) {
        console.error('Erreur update:', e);
    }
}

async function toggleVm(name, currentState) {
    const action = currentState === 1 ? 'stop' : 'start';
    try {
        await fetch(`/${action}`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                name
            })
        });
        showToast(`VM ${name} ${action === 'start' ? 'démarrée' : 'arrêtée'}`, 'success');
        setTimeout(updateMon, 1000);
    } catch (e) {
        showToast(`Erreur: ${e.message}`, 'error');
    }
}

async function deleteVm(name) {
    if (!confirm(`Supprimer la VM ${name} ?\nLe disque sera effacé.`)) return;
    try {
        await fetch('/delete', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                name
            })
        });
        showToast(`VM ${name} supprimée`, 'success');
        updateMon();
    } catch (e) {
        showToast(`Erreur: ${e.message}`, 'error');
    }
}

setInterval(async() => {
    try {
        const data = await fetch('/metrics').then(r => r.json());
        data.forEach(m => {
            const row = document.querySelector(`tr[data-vm="${m.name}"]`);
            if (row) {
                row.querySelector('.cpu').textContent = m.cpu + ' %';
                row.querySelector('.ram').textContent = m.ram + ' %';
                row.querySelector('.disk').textContent = m.disk_GB + ' GB';
            }
        });
    } catch (e) {
        console.error('Erreur metrics:', e);
    }
}, 3000);

document.getElementById('deployForm').addEventListener('submit', async(e) => {
    e.preventDefault();
    const body = Object.fromEntries(new FormData(e.target));

    closeModal();
    showToast(`Déploiement de ${body.name} en cours...`, 'warning');

    try {
        const response = await fetch('/deploy', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(body)
        });

        const result = await response.json();

        if (response.ok) {
            showToast(`VM ${body.name} créée ! IP: ${result.ip}`, 'success');
            updateMon();
            e.target.reset();
        } else {
            showToast(`Erreur: ${result.error}`, 'error');
        }
    } catch (e) {
        showToast(`Erreur réseau: ${e.message}`, 'error');
    }
});

window.onclick = (e) => {
    if (e.target.id === 'modal') closeModal();
};

// Init
fillIsos();
updateMon();
setInterval(updateMon, 5000);