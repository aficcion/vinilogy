const API_BASE = "";

// -------------------------------------------------
// Helpers
// -------------------------------------------------
function getUserId() {
    const id = localStorage.getItem('userId');
    if (!id) return null;
    return id;
}

function showToast(message, type = 'info') {
    let container = document.querySelector('.toast-container');
    if (!container) {
        container = document.createElement('div');
        container.className = 'toast-container';
        document.body.appendChild(container);
    }

    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.innerHTML = `<span>${message}</span>`;

    container.appendChild(toast);
    setTimeout(() => {
        toast.style.opacity = '0';
        setTimeout(() => toast.remove(), 300);
    }, 3000);
}

// Tracks in-flight GET requests to avoid duplicate concurrent fetches
const _pendingRequests = new Map();

async function apiCall(endpoint, method = 'GET', body = null, { timeoutMs = 30000, retries = 1, signal } = {}) {
    // Deduplicate identical concurrent GET requests
    const dedupeKey = method === 'GET' ? endpoint : null;
    if (dedupeKey && _pendingRequests.has(dedupeKey)) {
        return _pendingRequests.get(dedupeKey);
    }

    const controller = new AbortController();
    if (signal) signal.addEventListener('abort', () => controller.abort());
    const timeoutId = setTimeout(() => controller.abort(), timeoutMs);

    const options = {
        method,
        headers: { 'Content-Type': 'application/json' },
        signal: controller.signal,
    };
    if (body) options.body = JSON.stringify(body);

    const execute = async (attempt) => {
        try {
            const res = await fetch(API_BASE + endpoint, options);

            if (res.status === 429) {
                const retryAfter = parseInt(res.headers.get('Retry-After') || '60', 10);
                showToast(`Demasiadas peticiones. Espera ${retryAfter}s.`, 'error');
                throw new Error(`Rate limited. Retry after ${retryAfter}s`);
            }

            if (!res.ok) {
                const err = await res.json().catch(() => ({ detail: 'Unknown error' }));
                throw new Error(err.detail || `Error ${res.status}`);
            }
            return await res.json();
        } catch (e) {
            if (e.name === 'AbortError') throw new Error('La petición tardó demasiado o fue cancelada');
            if (attempt < retries) {
                await new Promise(r => setTimeout(r, 500 * attempt));
                return execute(attempt + 1);
            }
            throw e;
        }
    };

    const promise = execute(1).finally(() => {
        clearTimeout(timeoutId);
        if (dedupeKey) _pendingRequests.delete(dedupeKey);
    });

    if (dedupeKey) _pendingRequests.set(dedupeKey, promise);

    try {
        return await promise;
    } catch (e) {
        showToast(e.message, 'error');
        throw e;
    }
}

// -------------------------------------------------
// Auth
// -------------------------------------------------
async function loginGoogle(email, displayName, googleSub) {
    try {
        const data = await apiCall('/auth/google', 'POST', { email, display_name: displayName, google_sub: googleSub });
        localStorage.setItem('userId', data.user_id);
        window.location.href = '/index.html';
    } catch (e) { console.error(e); }
}

/* Updated Last.fm login flow – opens popup immediately to avoid blocker */
/* Robust Last.fm login flow – Manual Confirmation Fallback */
async function loginLastfm() {
    // 1. Open popup immediately
    const popup = window.open('', 'lastfm-auth', 'width=600,height=700');
    if (!popup) {
        showToast('El navegador bloqueó la ventana emergente. Permite pop‑ups y vuelve a intentarlo.', 'error');
        return;
    }

    try {
        // 2. Get Auth URL
        const res = await apiCall('/auth/lastfm/login');
        if (!res.auth_url || !res.token) {
            showToast('Error de configuración con Last.fm', 'error');
            popup.close();
            return;
        }

        // 3. Navigate popup
        popup.location = res.auth_url;

        // 4. Show "I have authorized" button (Plan B for when callback fails)
        const confirmBtn = document.createElement('button');
        confirmBtn.textContent = '✅ Ya autoricé en Last.fm';
        confirmBtn.style.cssText = 'position:fixed;top:50%;left:50%;transform:translate(-50%,-50%);z-index:10000;padding:20px 40px;background:#d51007;color:white;border:none;border-radius:12px;font-size:18px;font-weight:bold;cursor:pointer;box-shadow:0 8px 24px rgba(0,0,0,0.5);';

        confirmBtn.onclick = async () => {
            console.log('Verificando token manualmente:', res.token);
            confirmBtn.disabled = true;
            confirmBtn.textContent = 'Verificando...';

            try {
                // Manually check the token
                const callbackRes = await apiCall(`/auth/lastfm/callback?token=${res.token}`);
                console.log('Respuesta callback:', callbackRes);

                if (callbackRes.status === 'ok' && callbackRes.username) {
                    console.log('Autenticación exitosa, creando usuario...');
                    const authRes = await apiCall('/auth/lastfm', 'POST', { lastfm_username: callbackRes.username });

                    localStorage.setItem('userId', authRes.user_id);
                    // Store username too for generation fallback
                    if (callbackRes.username) localStorage.setItem('lastfm_username', callbackRes.username);

                    console.log('Usuario guardado:', authRes.user_id);

                    if (!popup.closed) popup.close();
                    document.body.removeChild(confirmBtn);
                    window.location.href = '/index.html';
                } else {
                    throw new Error('La respuesta del servidor no fue OK');
                }
            } catch (e) {
                console.error('Error en verificación manual:', e);
                confirmBtn.disabled = false;
                confirmBtn.style.backgroundColor = '#dc3545'; // Rojo error
                confirmBtn.textContent = '❌ No detectado. Reintentar';
                setTimeout(() => {
                    confirmBtn.textContent = '✅ Ya autoricé en Last.fm';
                    confirmBtn.style.backgroundColor = '#d51007'; // Rojo original
                }, 3000);
            }
        };

        document.body.appendChild(confirmBtn);

        // Eliminamos el listener automático para evitar conflictos
        // window.addEventListener('message', ... ); 

    } catch (e) {
        console.error(e);
        showToast('Error al iniciar sesión', 'error');
        if (!popup.closed) popup.close();
    }
}

// Backward‑compatible alias (in case other code uses the old name)
const loginLastFm = loginLastfm;

// Handle callback from Last.fm (check URL params on load)
async function handleLastFmCallback() {
    const params = new URLSearchParams(window.location.search);
    const token = params.get('token');
    if (token) {
        try {
            // Exchange token for session/user
            const res = await apiCall(`/auth/lastfm/callback?token=${token}`);
            if (res.status === 'ok' && res.username) {
                // Now create/get user in our DB
                const authRes = await apiCall('/auth/lastfm', 'POST', { lastfm_username: res.username });
                localStorage.setItem('userId', authRes.user_id);
                if (res.username) localStorage.setItem('lastfm_username', res.username);
                localStorage.setItem('vinilogy_lastfm_auth_completed', 'true');

                // Clean URL
                window.history.replaceState({}, document.title, "/index.html");
                window.location.href = '/index.html';
            }
        } catch (e) {
            console.error(e);
            showToast('Last.fm authentication failed', 'error');
        }
    }
}

// Call on load if we are on login page or index
if (window.location.pathname.includes('login') || window.location.pathname === '/' || window.location.pathname.includes('index')) {
    handleLastFmCallback();
}

async function handleManualLogin() {
    const username = document.getElementById('manual-username').value.trim();
    if (!username) return;

    try {
        // Directly create/get user with this username
        const authRes = await apiCall('/auth/lastfm', 'POST', { lastfm_username: username });
        localStorage.setItem('userId', authRes.user_id);
        window.location.href = '/index.html';
    } catch (e) {
        console.error(e);
        showToast('Login failed', 'error');
    }
}

async function linkLastFm(username) {
    const uid = getUserId();
    if (!uid) return;
    try {
        await apiCall('/auth/lastfm/link', 'POST', { user_id: parseInt(uid), lastfm_username: username });
        showToast('Account linked successfully', 'success');
        setTimeout(() => window.location.reload(), 1000);
    } catch (e) { console.error(e); }
}

// -------------------------------------------------
// Profile
// -------------------------------------------------
async function loadProfile() {
    const uid = getUserId();
    if (!uid) return;

    try {
        const profile = await apiCall(`/users/${uid}/profile/lastfm`);
        document.getElementById('profile-username').textContent = profile.lastfm_username;
        document.getElementById('profile-updated').textContent = new Date(profile.generated_at).toLocaleDateString();

        const container = document.getElementById('top-artists-grid');
        container.innerHTML = '';

        if (profile.top_artists && profile.top_artists.length) {
            profile.top_artists.forEach(artist => {
                const card = document.createElement('div');
                card.className = 'card';
                card.innerHTML = `
                    <h3>${artist.name}</h3>
                    <p>${artist.playcount || 0} plays</p>
                `;
                container.appendChild(card);
            });
        } else {
            container.innerHTML = '<p style="grid-column: 1/-1; text-align: center; color: var(--text-secondary);">No top artists found.</p>';
        }
    } catch (e) {
        if (e.message.includes('404')) {
            document.getElementById('profile-content').innerHTML = `
                <div style="text-align: center; padding: 2rem;">
                    <p>No Last.fm profile linked.</p>
                    <button class="btn" onclick="document.getElementById('link-modal').showModal()">Link Last.fm</button>
                </div>
            `;
        }
    }
}

// -------------------------------------------------
// Artists
// -------------------------------------------------
async function loadSelectedArtists() {
    const uid = getUserId();
    if (!uid) return;

    const artists = await apiCall(`/users/${uid}/selected-artists`);
    const tbody = document.getElementById('artists-table-body');
    tbody.innerHTML = '';

    artists.forEach(a => {
        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td>${a.artist_name}</td>
            <td>${a.source}</td>
            <td>${new Date(a.created_at).toLocaleDateString()}</td>
            <td style="text-align: right;">
                <button class="btn btn-sm btn-danger" onclick="removeArtist(${a.id})">Remove</button>
            </td>
        `;
        tbody.appendChild(tr);
    });
}

async function addArtist(name) {
    const uid = getUserId();
    if (!uid) return;
    try {
        await apiCall(`/users/${uid}/selected-artists`, 'POST', { artist_name: name, source: 'manual' });
        showToast(`Added ${name}`, 'success');
        loadSelectedArtists();
        return true;
    } catch (e) { return false; }
}

async function removeArtist(id) {
    const uid = getUserId();
    if (!uid) return;
    if (!confirm('Are you sure?')) return;

    try {
        await apiCall(`/users/${uid}/selected-artists/${id}`, 'DELETE');
        showToast('Artist removed', 'success');
        loadSelectedArtists();
    } catch (e) { console.error(e); }
}

// -------------------------------------------------
// Recommendations
// -------------------------------------------------
async function loadRecommendations(includeFav = true) {
    const uid = getUserId();
    if (!uid) return;

    const endpoint = includeFav ?
        `/users/${uid}/recommendations` :
        `/users/${uid}/recommendations?include_favorites=false`;

    const recs = await apiCall(endpoint);
    renderRecommendations(recs);
}

// renderRecommendations is defined in app-user.js - don't duplicate it here

async function updateRecStatus(recId, newStatus) {
    const uid = getUserId();
    if (!uid) return;

    try {
        await apiCall(`/users/${uid}/recommendations/${recId}`, 'PATCH', { new_status: newStatus });
        // Optimistic update or reload
        loadRecommendations(document.getElementById('show-favs')?.checked ?? true);
    } catch (e) { console.error(e); }
}

async function regenerateRecs() {
    const uid = getUserId();
    if (!uid) return;

    const btn = document.getElementById('regen-btn');
    const originalText = btn.innerHTML;
    btn.innerHTML = '<span class="spinner"></span> Generating...';
    btn.disabled = true;

    try {
        // In a real app, this would call the recommender service to get new recs
        // For now, we'll simulate it or pass dummy data if the backend expects it
        // The backend endpoint expects 'new_recs' list.
        // We'll fetch from the *existing* recommender endpoints (e.g. /api/recommendations/artists) 
        // and then pass that to the persistence layer.
        // -------------------------------------------------
        // Artist Search
        // -------------------------------------------------
        async function searchArtists(query) {
            if (!query || query.length < 2) return [];
            try {
                const res = await apiCall(`/api/spotify/search/artists?q=${encodeURIComponent(query)}`);
                // The backend returns { artists: [...] }
                return res.artists || [];
            } catch (e) {
                console.error(e);
                return [];
            }
        }

        async function selectArtistFromSearch(artistName, mbid, spotifyId) {
            const uid = getUserId();
            if (!uid) return;
            try {
                await apiCall(`/users/${uid}/selected-artists`, 'POST', {
                    artist_name: artistName,
                    mbid: mbid,
                    spotify_id: spotifyId,
                    source: 'manual'
                });
                showToast(`Added ${artistName}`, 'success');
                // Refresh lists if on relevant pages
                if (document.getElementById('artists-table-body')) loadSelectedArtists();
                return true;
            } catch (e) { return false; }
        }
        // 1. Get selected artists
        const artists = await apiCall(`/users/${uid}/selected-artists`);
        const artistNames = artists.map(a => a.artist_name);

        let newRecs = [];

        if (artistNames.length >= 3) {
            // Call the recommender service (proxied via gateway)
            const recResp = await apiCall('/api/recommendations/artists', 'POST', { artist_names: artistNames.slice(0, 5) });
            newRecs = recResp.recommendations.map(r => ({
                artist_name: r.artist,
                album_title: r.album,
                album_mbid: r.mbid,
                source: 'mixed'
            }));
        } else {
            // Fallback or error
            showToast('Select at least 3 artists first!', 'warning');
            btn.innerHTML = originalText;
            btn.disabled = false;
            return;
        }

        // 2. Save to DB
        await apiCall(`/users/${uid}/recommendations/regenerate`, 'POST', { new_recs: newRecs });

        showToast('Recommendations regenerated!', 'success');
        loadRecommendations();

    } catch (e) {
        console.error(e);
    } finally {
        btn.innerHTML = originalText;
        btn.disabled = false;
    }
}

// -------------------------------------------------
// Discogs & Profile
// -------------------------------------------------
async function loginDiscogs() {
    // Open popup
    const popup = window.open('', 'discogs-auth', 'width=600,height=700');
    if (!popup) {
        showToast('Popup blocked', 'error');
        return;
    }

    try {
        const res = await apiCall('/auth/discogs/login');
        if (res.auth_url) {
            popup.location = res.auth_url;
        } else {
            popup.close();
            showToast('Failed to start Discogs login', 'error');
        }
    } catch (e) {
        if (!popup.closed) popup.close();
        console.error(e);
        showToast('Error', 'error');
    }
}

async function linkDiscogs() {
    const uid = getUserId();
    if (!uid) return;

    // Set flag for callback.html to know this is a LINK operation
    localStorage.setItem('pending_discogs_link_user_id', uid);

    const popup = window.open('', 'discogs-link', 'width=600,height=700');

    try {
        const res = await apiCall('/auth/discogs/login'); // Reuse login endpoint to get token
        if (res.auth_url) {
            popup.location = res.auth_url;

            // Listen for success message from popup
            window.addEventListener('message', function (e) {
                if (e.data.type === 'DISCOGS_LINK_SUCCESS') {
                    showToast('Discogs linked as ' + e.data.username, 'success');

                    // Trigger Wizard Logic
                    localStorage.setItem('discogs_username', e.data.username);
                    localStorage.setItem('vinilogy_discogs_auth_completed', 'true');

                    if (typeof checkDiscogsAuthReturn === 'function') {
                        checkDiscogsAuthReturn();
                    }

                    loadConnections(); // Refresh UI
                }
            }, { once: true });
        }
    } catch (e) {
        if (!popup.closed) popup.close();
        console.error(e);
    }
}


function showProfile() {
    document.getElementById('landing-view').style.display = 'none';
    document.getElementById('recommendations-view').style.display = 'none';
    document.getElementById('album-detail-view').style.display = 'none';
    document.getElementById('profile-view').style.display = 'block';

    // Update header buttons
    const profileBtn = document.getElementById('profile-btn');
    if (profileBtn) profileBtn.style.display = 'none';
    const collectionBtn = document.getElementById('collection-btn');
    if (collectionBtn) collectionBtn.style.display = 'none';

    loadSettings();
    loadConnections();
}

function showHome() {
    const uid = getUserId();
    if (uid) {
        showRecommendations();
    } else {
        window.location.href = '/';
    }
}

function showRecommendations() {
    document.getElementById('profile-view').style.display = 'none';
    document.getElementById('landing-view').style.display = 'none';
    document.getElementById('recommendations-view').style.display = 'block';

    const profileBtn = document.getElementById('profile-btn');
    if (profileBtn) profileBtn.style.display = 'block';
    const collectionBtn = document.getElementById('collection-btn');
    if (collectionBtn) collectionBtn.style.display = 'block';

    // Check connections to toggle header buttons
    loadConnections();
}

async function loadSettings() {
    const uid = getUserId();
    if (!uid) return;
    try {
        const settings = await apiCall('/user/' + uid + '/settings');
        const toggle = document.getElementById('setting-cfm');
        if (toggle) toggle.checked = !!settings.cf_enabled;
    } catch (e) { console.error(e); }
}

async function toggleCFM() {
    const uid = getUserId();
    if (!uid) return;
    const toggle = document.getElementById('setting-cfm');
    if (!toggle) return;
    const enabled = toggle.checked;
    try {
        await apiCall('/user/' + uid + '/settings', 'POST', { cf_enabled: enabled });
        showToast('Preferences updated', 'success');
    } catch (e) {
        showToast('Failed to update settings', 'error');
        // Revert toggle
        toggle.checked = !enabled;
    }
}

async function checkSyncStatus(userId) {
    try {
        const resp = await fetch(`/user/${userId}/sync-status`);
        const status = await resp.json();

        const discogsStatus = document.querySelector('#conn-discogs .conn-status');
        if (!discogsStatus) return;

        // Only update if connected
        if (!discogsStatus.textContent.includes('Connected')) return;

        if (status.status === 'running') {
            discogsStatus.innerHTML = `Connected <span style="color:#eab308; margin-left:8px;">Importing... (${status.processed} items)</span>`;
            setTimeout(() => checkSyncStatus(userId), 2000);
        } else if (status.status === 'completed') {
            discogsStatus.innerHTML = `Connected <span style="color:#22c55e; margin-left:8px;">Imported (${status.processed} items)</span>`;
        } else if (status.status === 'failed') {
            // Keep connected but show error
            discogsStatus.innerHTML += ` <span style="color:#ef4444;">(Import failed)</span>`;
        }
    } catch (e) {
        console.error("Sync check failed", e);
    }
}

async function loadConnections() {
    const uid = getUserId();
    if (!uid) return;
    try {
        const conns = await apiCall('/user/' + uid + '/connections');

        // Update Discogs UI (Profile)
        const discogsBtn = document.getElementById('btn-conn-discogs');
        const discogsStatus = document.querySelector('#conn-discogs .conn-status');
        if (discogsBtn && discogsStatus) {
            if (conns.discogs && conns.discogs.connected) {
                discogsStatus.textContent = 'Connected as ' + conns.discogs.username;
                discogsStatus.style.color = '#22c55e';
                discogsBtn.textContent = 'Disconnect';
                discogsBtn.onclick = async () => {
                    await fetch('/auth/discogs/unlink', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ user_id: uid })
                    });
                    loadConnections();
                };

                // Start polling sync status
                checkSyncStatus(uid);

            } else {
                discogsStatus.textContent = 'Not connected';
                discogsStatus.style.color = 'var(--text-secondary)';
                discogsBtn.textContent = 'Connect with Discogs';
                discogsBtn.onclick = linkDiscogs;
            }
        }

        // Update Discogs Header Button (Recommendations View)
        const discogsHeaderBtn = document.getElementById('discogs-header-btn');
        if (discogsHeaderBtn) {
            if (conns.discogs && conns.discogs.connected) {
                discogsHeaderBtn.style.display = 'none';
            } else {
                discogsHeaderBtn.style.display = 'inline-flex';
            }
        }

        // Update Last.fm UI
        const lastfmBtn = document.getElementById('btn-conn-lastfm');
        const lastfmStatus = document.querySelector('#conn-lastfm .conn-status');
        if (lastfmBtn && lastfmStatus) {
            if (conns.lastfm && conns.lastfm.connected) {
                lastfmStatus.textContent = 'Connected as ' + conns.lastfm.username;
                lastfmStatus.style.color = '#22c55e';
                lastfmBtn.textContent = 'Disconnect';
                lastfmBtn.onclick = () => showToast('Disconnect not implemented yet', 'info');
            } else {
                lastfmStatus.textContent = 'Not connected';
                lastfmBtn.textContent = 'Connect';
                lastfmBtn.onclick = loginLastfm;
            }
        }

    } catch (e) { console.error(e); }
}

// Init profile button visibility
// Init profile button visibility
document.addEventListener('DOMContentLoaded', () => {
    const uid = getUserId();
    console.log('Checking user ID for profile button:', uid);
    if (uid) {
        const profileBtn = document.getElementById('profile-btn');
        if (profileBtn) {
            profileBtn.style.display = 'block';
            console.log('Profile button shown');
        } else {
            console.error('Profile button not found in DOM');
        }
        const collectionBtn = document.getElementById('collection-btn');
        if (collectionBtn) {
            collectionBtn.style.display = 'block';
            console.log('Collection button shown');
        }
        // Initial connection check
        loadConnections();
    }
});

