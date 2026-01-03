const STATE = ['Éteinte', 'Active', 'Suspendue'];

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

async function loadHosts() {
    try {
        const hosts = await fetch('/hosts').then(r => r.json());
        const select = document.getElementById('hostSelect');
        select.innerHTML = hosts.map(h =>
            `<option value="${h.id}">${h.name}</option>`
        ).join('');
    } catch (e) {
        console.error('Erreur hosts:', e);
    }
}

async function loadImages() {
    try {
        const images = await fetch('/images').then(r => r.json());
        const select = document.getElementById('imageSelect');
        select.innerHTML = images.map(img =>
            `<option value="${img.name}">${img.name} ${img.downloaded ? '✓' : '(sera téléchargée)'}</option>`
        ).join('');
    } catch (e) {
        console.error('Erreur images:', e);
    }
}

async function updateMon() {
    try {
        const data = await fetch('/vms').then(r => r.json());
        const tb = document.querySelector('#mon');

        if (data.length === 0) {
            tb.innerHTML = `<tr><td colspan="10">
                        <div class="empty-state">
                            <p>Aucune instance</p>
                        </div>
                    </td></tr>`;
            return;
        }

        tb.innerHTML = data.map(v => `<tr data-vm="${v.name}" data-host="${v.host}">
                    <td><strong>${v.name}</strong></td>
                    <td><span class="badge">${v.host_name}</span></td>
                    <td><span class="status ${v.state===1?'on':'off'}">${STATE[v.state]||'Inconnu'}</span></td>
                    <td>${v.cpu}</td>
                    <td class="ram-max">${v.ram} Mo</td>
                    <td class="cpu">-</td>
                    <td class="ram">-</td>
                    <td class="disk">-</td>
                    <td>${v.ip||'-'}</td>
                    <td>
                        <div class="actions">
                            <button class="btn ${v.state===1?'btn-danger':'btn-success'}" 
                                    onclick="toggleVm('${v.name}','${v.host}',${v.state})">
                                ${v.state===1?'Stop':'Start'}
                            </button>
                            <button class="btn btn-danger" onclick="deleteVm('${v.name}','${v.host}')">
                                🗑
                            </button>
                        </div>
                    </td>
                </tr>`).join('');
    } catch (e) {
        console.error('Erreur update:', e);
    }
}

async function toggleVm(name, host, currentState) {
    const action = currentState === 1 ? 'stop' : 'start';
    try {
        await fetch(`/${action}`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                name,
                host
            })
        });
        showToast(`VM ${name} ${action === 'start' ? 'démarrée' : 'arrêtée'}`, 'success');
        setTimeout(updateMon, 1000);
    } catch (e) {
        showToast(`Erreur: ${e.message}`, 'error');
    }
}

async function deleteVm(name, host) {
    if (!confirm(`Supprimer la VM ${name} ?`)) return;
    try {
        await fetch('/delete', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                name,
                host
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
            const row = document.querySelector(`tr[data-vm="${m.name}"][data-host="${m.host}"]`);
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
    showToast(`Déploiement de ${body.name} en cours... (30 sec)`, 'warning');

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
        showToast(`Erreur: ${e.message}`, 'error');
    }
});

window.onclick = (e) => {
    if (e.target.id === 'modal') closeModal();
};

// Init
loadHosts();
loadImages();
updateMon();
setInterval(updateMon, 5000);