// api.js - Utilitaires API partagés

const API_URL = 'http://localhost:5000';

// Récupérer le token
function getToken() {
    return localStorage.getItem('token');
}

// Requête API avec authentification
async function apiRequest(endpoint, options = {}) {
    const headers = {
        'Content-Type': 'application/json',
        ...options.headers
    };

    const token = getToken();
    if (token) {
        headers['Authorization'] = `Bearer ${token}`;
    }

    const response = await fetch(`${API_URL}${endpoint}`, {
        ...options,
        headers
    });

    if (response.status === 401) {
        logout();
        throw new Error('Non autorisé');
    }

    return response;
}

// Toast notifications
function showToast(msg, type = 'success') {
    const toast = document.getElementById('toast');
    if (!toast) return;

    toast.textContent = msg;
    toast.className = `toast ${type} show`;
    setTimeout(() => toast.classList.remove('show'), 4000);
}

// Déconnexion
function logout() {
    localStorage.clear();
    window.location.href = 'index.html';
}

// Vérifier l'authentification
async function checkAuth() {
    const token = getToken();
    if (!token) {
        window.location.href = 'index.html';
        return null;
    }

    try {
        const response = await apiRequest('/auth/me');
        if (response.ok) {
            return await response.json();
        } else {
            logout();
            return null;
        }
    } catch (e) {
        logout();
        return null;
    }
}

// Charger les flavors
async function loadFlavors() {
    try {
        const response = await apiRequest('/flavors');
        return await response.json();
    } catch (e) {
        console.error('Erreur flavors:', e);
        return [];
    }
}

// Charger les images disponibles
async function loadAvailableImages() {
    try {
        const response = await fetch(`${API_URL}/images/available`);
        if (!response.ok) throw new Error();
        return await response.json();
    } catch (e) {
        console.error('Erreur images:', e);
        return [];
    }
}