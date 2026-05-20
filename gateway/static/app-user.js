(async () => {
    const uid = localStorage.getItem('userId');
    if (uid) {
        startSyncMonitor(uid);

        // Check for Wizard completion flag
        const wizardCompleted = localStorage.getItem('discogs_wizard_completed');
        if (wizardCompleted) {
            console.log("Wizard completed logic triggered");
            localStorage.removeItem('discogs_wizard_completed');
        }

        // Always fetch recommendations on load
        fetchUserRecommendations(uid);

        try {
            // 2. Sync Last.fm state from backend
            try {
                const profileResp = await fetch(`/api/users/${uid}/profile/lastfm`);
                if (profileResp.ok) {
                    const profile = await profileResp.json();
                    if (profile.lastfm_username) {
                        console.log('✓ Synced Last.fm username from backend (IIFE):', profile.lastfm_username);
                        localStorage.setItem('lastfm_username', profile.lastfm_username);
                        window.lastfmConnected = true;
                    }
                }
            } catch (e) {
                console.warn('Could not sync Last.fm profile:', e);
            }

        } catch (e) {
            console.error('Error verificando usuario al iniciar:', e);
        }
    }
})();

const hasLastfm = true; // Last.fm integration enabled

function initTheme() {
    const savedTheme = localStorage.getItem('theme') || 'light';
    document.documentElement.setAttribute('data-theme', savedTheme);
}

function toggleTheme() {
    const currentTheme = document.documentElement.getAttribute('data-theme');
    const newTheme = currentTheme === 'dark' ? 'light' : 'dark';
    document.documentElement.setAttribute('data-theme', newTheme);
    localStorage.setItem('theme', newTheme);
}


// Last.fm Authentication - Simplified redirect flow
async function loginLastfm() {
    try {
        const response = await fetch('/auth/lastfm/login');
        const data = await response.json();

        if (data.auth_url) {
            // Set auth pending flag
            localStorage.setItem('vinilogy_lastfm_auth_pending', 'true');
            // Remove any old token
            localStorage.removeItem('vinilogy_lastfm_token');

            // Redirect to Last.fm in the same window
            window.location.href = data.auth_url;
        }
    } catch (error) {
        console.error('Error initiating Last.fm login:', error);
        alert('Error al conectar con Last.fm. Por favor, intenta de nuevo.');
    }
}

// Check if we just returned from Last.fm authentication
function checkLastfmAuthReturn() {
    const authCompleted = localStorage.getItem('vinilogy_lastfm_auth_completed');
    const lastfmUsername = localStorage.getItem('lastfm_username');

    if (authCompleted === 'true' && lastfmUsername) {
        // Clear the flag
        localStorage.removeItem('vinilogy_lastfm_auth_completed');

        console.log('✓ Returned from Last.fm authentication:', lastfmUsername);

        // Show success message
        if (typeof showToast === 'function') {
            showToast(`¡Conectado con Last.fm como ${lastfmUsername}!`, 'success');
        }

        // FORCE UI UPDATE immediately to avoid Guest+Spinner glitch
        const landing = document.getElementById('landing-view');
        if (landing) landing.style.display = 'none';
        document.body.classList.remove('landing-active');
        const dashboard = document.getElementById('recommendations-view');
        if (dashboard) dashboard.style.display = 'block';

        // Hide auth buttons in header
        document.querySelectorAll('.auth-btn').forEach(b => b.style.display = 'none');
        document.getElementById('user-menu')?.classList.remove('hidden');

        // Load recommendations for the user
        const userId = localStorage.getItem('userId');
        if (userId) {
            fetchUserRecommendations(userId);
        }
    }
}

// Check if we just returned from Discogs authentication
function checkDiscogsAuthReturn() {
    const authCompleted = localStorage.getItem('vinilogy_discogs_auth_completed');
    const discogsUsername = localStorage.getItem('discogs_username');

    console.log('[DEBUG] checkDiscogsAuthReturn - Flag:', authCompleted, 'Username:', discogsUsername);

    if (authCompleted === 'true' && discogsUsername) {
        localStorage.removeItem('vinilogy_discogs_auth_completed');
        console.log('✓ Returned from Discogs authentication:', discogsUsername);

        if (typeof showToast === 'function') {
            showToast(`¡Conectado con Discogs como ${discogsUsername}!`, 'success');
        }

        // Launch Wizard for initial setup
        setTimeout(() => {
            if (typeof DiscogsWizard !== 'undefined') {
                DiscogsWizard.launch();
            }
        }, 500);
    }
}

// ---------------------------------------------------------------------
// Sync Monitor Logic
// ---------------------------------------------------------------------
let syncMonitorInterval = null;

function startSyncMonitor(userId) {
    if (!userId) return;
    if (syncMonitorInterval) clearInterval(syncMonitorInterval);

    const check = async () => {
        try {
            const res = await fetch(`/user/${userId}/sync-status`);
            if (res.ok) {
                const status = await res.json();
                updateSyncIndicator(status);
                // If recently completed/failed, stop polling after a delay or keep checking for restarts?
                // For now, keep checking at longer interval or stop if completed?
                // Sync might stop then restart? 
                // Let's stop if completed to save calls, but maybe restart if user triggers it?
                // For robustness, we'll keep polling but maybe slower? No, 3s is fine.
                if (status.status === 'completed' && document.getElementById('sync-indicator')?.textContent.includes('Sincronizando')) {
                    // Just finished
                    if (typeof showToast === 'function') showToast('Sincronización completada', 'success');
                    // Refresh recs?
                    fetchUserRecommendations(userId);
                }
            }
        } catch (e) { console.warn('Sync monitor error:', e); }
    };

    check();
    syncMonitorInterval = setInterval(check, 3000);
}

function updateSyncIndicator(status) {
    let el = document.getElementById('sync-indicator');
    if (!el) {
        el = document.createElement('div');
        el.id = 'sync-indicator';
        // Styled to be visible but not annoying 
        el.style.cssText = 'position:fixed;top:0;left:0;right:0;background:linear-gradient(90deg, #3b82f6, #2563eb);color:white;text-align:center;padding:8px;font-size:13px;font-weight:500;z-index:9999;transition:transform 0.3s ease-in-out;transform:translateY(-100%);box-shadow:0 2px 5px rgba(0,0,0,0.1);';
        document.body.appendChild(el);
    }

    if (status.status === 'running') {
        el.textContent = `🔄 Sincronizando colección de Discogs... (${status.processed} ítems)`;
        el.style.transform = 'translateY(0)';
    } else {
        el.style.transform = 'translateY(-100%)';
    }
}

// ---------------------------------------------------------------------

// Helper: fetch recommendations for a logged‑in user and sync status map
// ---------------------------------------------------------------------
async function fetchUserRecommendations(userId) {
    // Validate userId
    if (!userId || userId === 'undefined' || userId === 'null') {
        console.warn('fetchUserRecommendations called with invalid userId:', userId);
        return;
    }

    // ENFORCE DASHBOARD VIEW
    const landing = document.getElementById('landing-view');
    if (landing) landing.style.display = 'none';
    document.body.classList.remove('landing-active');
    const dashboard = document.getElementById('recommendations-view');
    if (dashboard) dashboard.style.display = 'block';

    showSkeletonCards(8);
    showLoading(true);

    console.log(`Fetching recommendations for user: ${userId} at /api/users/${userId}/recommendations`);
    try {
        // Use the /api prefix which we explicitly aliased in the backend
        const resp = await fetch(`/api/users/${userId}/recommendations`);

        if (!resp.ok) {
            throw new Error(`Server responded with ${resp.status}: ${resp.statusText}`);
        }

        const data = await resp.json();
        console.log('Recommendations loaded:', data.length, 'items');

        // If no recommendations found and we have a Last.fm user, trigger generation
        // Check if we need to trigger initial Last.fm generation
        // We do this if:
        // 1. We have a Last.fm user connected
        // 2. We haven't synced with Last.fm yet (checked via a flag)
        const lastfmUser = localStorage.getItem('lastfm_username');
        const hasSyncedLastfm = localStorage.getItem('lastfm_synced_v2');

        // Trigger generation if:
        // 1. We have a Last.fm user
        // 2. AND (We haven't synced yet OR we synced but got 0 results)
        if (lastfmUser && (!hasSyncedLastfm || data.length === 0)) {
            console.log('Last.fm connected but no recs/not synced. Triggering generation/merge for:', lastfmUser);
            // Mark as synced BEFORE calling to prevent loops if it fails or returns 0
            localStorage.setItem('lastfm_synced_v2', 'true');
            await generateAndSaveRecommendations(userId, lastfmUser);
            return; // Exit, the generation function will call fetch again
        }

        // localStorage caching removed to prevent stale data issues
        // localStorage.setItem('last_recommendations', JSON.stringify(data));
        // localStorage.setItem('last_updated', new Date().toISOString());

        // Sync album status map from the received recommendations
        syncAlbumStatusesFromRecs(data);
        renderRecommendations(data);
    } catch (e) {
        console.error('Error fetching user recommendations:', e);
        // Fallback removed
        // checkCachedRecommendations();
        console.warn('Could not fetch recommendations, and cache is disabled.');
    }
}

// New helper to generate and save recommendations
async function generateAndSaveRecommendations(userId, lastfmUsername) {
    showLoading(true, 'Generando recomendaciones personalizadas...');
    try {
        // 1. Get recommendations from Last.fm
        console.log('Step 1: Fetching Last.fm recommendations...');
        const genResp = await fetch('/api/lastfm/recommendations', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                username: lastfmUsername,
                time_range: 'medium_term'
            })
        });

        if (!genResp.ok) throw new Error('Failed to generate recommendations');
        const genData = await genResp.json();
        const newLastfmRecs = genData.albums || [];
        console.log(`✓ Generated ${newLastfmRecs.length} recommendations from Last.fm`);

        // 2. Get recommendations for Selected Artists (Manual)
        console.log('Step 2: Fetching Manual Artist recommendations...');
        let manualRecs = [];
        try {
            // 2a. Get selected artists
            const artistsResp = await fetch(`/api/users/${userId}/selected-artists`);
            if (artistsResp.ok) {
                const selectedArtists = await artistsResp.json();
                const artistNames = selectedArtists.map(a => a.artist_name);

                if (artistNames.length > 0) {
                    console.log(`Found ${artistNames.length} selected artists:`, artistNames);

                    // Show progress modal
                    showProgressModal('Generando Recomendaciones');

                    // 2b. Generate recommendations for each artist (Frontend Loop with Fallback)
                    let completed = 0;
                    const total = artistNames.length;

                    for (const artistName of artistNames) {
                        updateProgressUI(completed, total, `Procesando ${artistName}...`, artistName);

                        try {
                            // Try Canonical (Cache-only first - FAST)
                            let recs = [];
                            try {
                                const resp = await fetch('/api/recommendations/artist-single', {
                                    method: 'POST',
                                    headers: { 'Content-Type': 'application/json' },
                                    body: JSON.stringify({
                                        artist_name: artistName,
                                        top_albums: 3,
                                        user_id: userId,  // For logging
                                        cache_only: false  // Allow backend to perform Discogs fallback
                                    })
                                });

                                if (resp.ok) {
                                    const data = await resp.json();
                                    if (data.recommendations && data.recommendations.length > 0) {
                                        recs = data.recommendations;
                                        console.log(`✓ Recommendations for ${artistName}: ${recs.length} recs`);
                                    } else {
                                        console.log(`⚠ No recommendations found for ${artistName}`);
                                    }
                                }
                            } catch (e) {
                                console.warn(`Canonical check failed for ${artistName}`, e);
                            }

                            // Fallback to Spotify REMOVED - We now use Discogs fallback in backend
                            /*
                            if (recs.length === 0) {
                                console.log(`→ Using Spotify for ${artistName}`);
                                try {
                                    const resp = await fetch('/api/recommendations/spotify', {
                                        method: 'POST',
                                        headers: { 'Content-Type': 'application/json' },
                                        body: JSON.stringify({
                                            artist_name: artistName,
                                            top_albums: 5,
                                            user_id: userId
                                        })
                                    });

                                    if (resp.ok) {
                                        const data = await resp.json();
                                        if (data.recommendations && data.recommendations.length > 0) {
                                            recs = data.recommendations;
                                            console.log(`✓ Spotify recs for ${artistName}: ${recs.length}`);
                                        }
                                    }
                                } catch (e) {
                                    console.warn(`Spotify fallback failed for ${artistName}`, e);
                                }
                            }
                            */

                            if (recs.length > 0) {
                                manualRecs.push(...recs);
                            }

                        } catch (e) {
                            console.error(`Error processing ${artistName}:`, e);
                        }

                        completed++;
                        updateProgressUI(completed, total, `Completado ${artistName}`, artistName);
                    }

                    hideProgressModal();
                    console.log(`✓ Generated ${manualRecs.length} recommendations from selected artists`);
                }
            }
        } catch (e) {
            console.warn('Error fetching manual artist recommendations:', e);
            hideProgressModal();
        }

        // 3. Get recommendations from Discogs Collection
        let discogsUsername = localStorage.getItem('discogs_username');

        // If missing, try to fetch from connections (backend)
        if (!discogsUsername && userId) {
            try {
                const connResp = await fetch(`/user/${userId}/connections`);
                if (connResp.ok) {
                    const conns = await connResp.json();
                    if (conns.discogs && conns.discogs.connected) {
                        // Use display name (text) if available, otherwise numeric ID as fallback
                        discogsUsername = conns.discogs.username_text || conns.discogs.username;
                        if (discogsUsername) {
                            console.log('✓ Retrieved Discogs username from backend:', discogsUsername);
                            localStorage.setItem('discogs_username', discogsUsername);
                        }
                    }
                }
            } catch (e) {
                console.warn('Error fetching connections for Discogs username:', e);
            }
        }

        let collectionRecs = [];
        if (discogsUsername) {
            console.log('Step 3: Fetching Discogs Collection recommendations for:', discogsUsername);
            try {
                // 2. Sync collection (backend)
                // Ideally we should poll until status is 'completed'
                const checkSyncLoop = async () => {
                    let attempts = 0;
                    while (attempts < 10) {
                        try {
                            const res = await fetch(`/api/user/${userId}/sync-status`);
                            const status = await res.json();
                            if (status.status === 'completed' || status.status === 'idle') {
                                // Only launch if we actually have items? 
                                // Or just launch and let Wizard handle empty state
                                console.log('Sync ready, launching wizard...');
                                if (typeof DiscogsWizard !== 'undefined') {
                                    DiscogsWizard.launch();
                                }
                                return;
                            }
                        } catch (e) { console.error(e); }
                        await new Promise(r => setTimeout(r, 2000));
                        attempts++;
                    }
                    console.warn('Sync timed out or taking too long, launching anyway...');
                    if (typeof DiscogsWizard !== 'undefined') DiscogsWizard.launch();
                };

                fetch('/api/discogs/sync', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        username: discogsUsername,
                        user_id: userId
                    })
                }).then(() => checkSyncLoop());

                // Legacy collection fetch removed to prevent pollution of recommendations table
                // The Wizard now handles all recommendation generation.
            } catch (e) {
                console.warn('Error fetching collection recommendations:', e);
            }
        }

        // 4. Smart Merge: Prioritize Collection Upgrades
        // If an album is in collectionRecs (Upgrade), we want THAT version (with badges/info),
        // not the generic one from Last.fm or Artist recommendations.

        const upgradeKeys = new Set(collectionRecs.map(r => `${r.artist_name.toLowerCase()}::${r.album_name.toLowerCase()}`));

        // Filter out generics if we have an upgrade for them
        const filteredLastFm = newLastfmRecs.filter(r => !upgradeKeys.has(`${r.artist_name.toLowerCase()}::${r.album_name.toLowerCase()}`));
        const filteredManual = manualRecs.filter(r => !upgradeKeys.has(`${r.artist_name.toLowerCase()}::${r.album_name.toLowerCase()}`));

        console.log('Step 4: Merging with existing recommendations...');
        // Put collection recs first so they are prominent? Or just merge.
        // Order: Collection Upgrades -> Last.fm -> Manual
        let finalRecs = [...collectionRecs, ...filteredLastFm, ...filteredManual];

        try {
            const existingResp = await fetch(`/api/users/${userId}/recommendations`);
            if (existingResp.ok) {
                const existingRecs = await existingResp.json();
                if (existingRecs.length > 0) {
                    console.log(`✓ Found ${existingRecs.length} existing recommendations`);

                    // Create a map of existing recs by key for easy lookup
                    const existingMap = new Map();
                    existingRecs.forEach(r => {
                        const key = `${r.artist_name}::${r.album_title || r.album_name}`;
                        existingMap.set(key, r);
                    });

                    // Filter new recs: 
                    // - If it exists in DB, keep the DB version (preserves status/id)
                    // - If it doesn't exist, keep the new version
                    const mergedRecs = [];
                    const processedKeys = new Set();

                    // Add existing recs first (they are the source of truth for status)
                    existingRecs.forEach(r => {
                        const key = `${r.artist_name}::${r.album_title || r.album_name}`;
                        mergedRecs.push(r);
                        processedKeys.add(key);
                    });

                    // Add new recs if they don't exist
                    finalRecs.forEach(r => {
                        const key = `${r.artist_name}::${r.album_name || r.album_title}`;
                        if (!processedKeys.has(key)) {
                            mergedRecs.push(r);
                            processedKeys.add(key);
                        }
                    });

                    finalRecs = mergedRecs;
                    console.log(`✓ Final merge count: ${finalRecs.length}`);
                }
            }
        } catch (e) {
            console.warn('Could not load existing recommendations for merge:', e);
        }

        // 4. Save merged recommendations to the database
        console.log('Step 4: Saving to database...');
        const saveResp = await fetch(`/users/${userId}/recommendations/regenerate`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ new_recs: finalRecs })
        });

        if (!saveResp.ok) throw new Error('Failed to save recommendations');

        console.log('✓ Recommendations saved successfully');

        // 5. Save Last.fm profile (top artists)
        try {
            const profileResp = await fetch(`/api/lastfm/top-artists`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    username: lastfmUsername,
                    time_range: 'medium_term'
                })
            });

            if (profileResp.ok) {
                const profileData = await profileResp.json();
                const topArtists = profileData.artists || [];

                if (topArtists.length > 0) {
                    await fetch(`/api/users/${userId}/profile/lastfm`, {
                        method: 'PUT',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            lastfm_username: lastfmUsername,
                            top_artists: topArtists.slice(0, 50)
                        })
                    });
                    console.log('✓ Last.fm profile saved');
                }
            }
        } catch (e) {
            console.warn('Could not save Last.fm profile:', e);
        }

        // 6. Fetch again to display
        showLoading(false);
        await fetchUserRecommendations(userId);

        if (typeof showToast === 'function') {
            showToast('Recomendaciones actualizadas correctamente', 'success');
        }

    } catch (e) {
        console.error('Error generating recommendations:', e);
        showLoading(false);
        alert('Hubo un error generando tus recomendaciones. Por favor intenta más tarde.');
    }
}

function getRecArtistAndAlbum(rec) {
    // Normalize artist name
    let artist = rec.artist_name || rec.artist || 'Unknown Artist';
    if (!artist || artist === 'Unknown Artist') {
        artist = rec.album_info?.artists?.[0]?.name || 'Unknown Artist';
    }

    // Normalize album name
    let album = rec.album_name || rec.album_title || rec.name || 'Unknown Album';
    if (!album || album === 'Unknown Album') {
        album = rec.album_info?.name || 'Unknown Album';
    }

    return { artist, album };
}

function syncAlbumStatusesFromRecs(recommendations) {
    // Clear current map ONLY for logged-in users who rely on DB sync
    // Guest users have their statuses loaded from localStorage by loadAlbumStatuses()
    const userId = localStorage.getItem('userId');
    if (typeof albumStatuses !== 'undefined') {
        if (userId) {
            albumStatuses.clear();
        }
        recommendations.forEach(rec => {
            const { artist, album } = getRecArtistAndAlbum(rec);
            // Sync all statuses from DB: neutral, favorite, owned, disliked
            if (rec.status) {
                const key = `${artist}|${album}`;
                // Map 'neutral' to null for the frontend (no special status)
                albumStatuses.set(key, rec.status === 'neutral' ? null : rec.status);
            }
        });
        console.log('[DEBUG] Synced album statuses. Map size:', albumStatuses.size);
        console.log('[DEBUG] Sample status keys:', Array.from(albumStatuses.keys()).slice(0, 3));
    } else {
        console.error('[DEBUG] albumStatuses is undefined in syncAlbumStatusesFromRecs!');
    }
}




// Legacy callback handler - no longer needed as callback.html handles everything
// Kept as no-op for backwards compatibility
async function handleLastfmCallback() {
    // All callback logic now handled in callback.html
    // This function is kept to avoid breaking existing code that calls it
}

// Mosaic Logic
async function loadMosaic() {
    const grid = document.getElementById('mosaicGrid');
    if (!grid) return;

    try {
        const response = await fetch('/api/mosaic');
        const data = await response.json();
        const albums = data.albums || [];

        if (albums.length === 0) return;

        // Ensure we have enough items to fill the grid (target 500 to account for broken images)
        let displayAlbums = [...albums];
        const targetCount = 500;

        // Duplicate albums if we don't have enough
        while (displayAlbums.length < targetCount && displayAlbums.length > 0) {
            displayAlbums = [...displayAlbums, ...albums];
        }

        // Shuffle the full set
        const shuffled = displayAlbums.sort(() => 0.5 - Math.random());

        // Slice to exact target
        const finalSet = shuffled.slice(0, targetCount);

        grid.innerHTML = finalSet.map(album => `
            <div class="mosaic-item" title="${escapeHtml(album.title)}">
                <img src="${album.cover_url}" 
                     loading="lazy"
                     alt="${escapeHtml(album.title)}"
                     onerror="this.parentElement.style.display='none'">
            </div>
        `).join('');
    } catch (error) {
        console.error('Error loading mosaic:', error);
    }
}

function escapeHtml(text) {
    if (!text) return '';
    return text
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}

// Show/hide loading state (legacy, keep for simple loads)
function showLoading(show, message = 'Cargando tus recomendaciones...') {
    const loadingEl = document.getElementById('loading');
    loadingEl.classList.toggle('active', show);
    if (show) {
        loadingEl.querySelector('p').textContent = message;
    }
}

function showSkeletonCards(count = 8) {
    const container = document.getElementById('albums-container');
    if (!container) return;
    const skeletonHTML = `
        <div class="skeleton-card album-card">
            <div class="skeleton skeleton-cover"></div>
            <div class="skeleton skeleton-line"></div>
            <div class="skeleton skeleton-line short"></div>
            <div class="skeleton-actions">
                <div class="skeleton skeleton-action"></div>
                <div class="skeleton skeleton-action"></div>
                <div class="skeleton skeleton-action"></div>
            </div>
        </div>`;
    container.innerHTML = skeletonHTML.repeat(count);
    document.getElementById('recommendations-view').classList.add('active');
    document.getElementById('landing-view').style.display = 'none';
    document.body.classList.remove('landing-active');
}

// Progress banner control
let progressStartTime = 0;

function showProgressModal(title = 'Generando Recomendaciones') {
    const banner = document.getElementById('progress-banner');
    const titleEl = document.getElementById('progress-title');

    showLoading(false);

    titleEl.textContent = title;
    banner.classList.add('active');
    progressStartTime = Date.now();

    updateProgressUI(0, 0, 'Iniciando...', '');
}

function hideProgressModal() {
    const banner = document.getElementById('progress-banner');
    banner.classList.remove('active');
    showLoading(false);
}

function updateProgressUI(current, total, status, currentArtist = '') {
    const progressBar = document.getElementById('progress-bar');
    const percentage = document.getElementById('progress-percentage');
    const statusEl = document.getElementById('progress-status');
    const artistEl = document.getElementById('progress-current-artist');
    const timeEl = document.getElementById('progress-time-estimate');

    const percent = total > 0 ? Math.round((current / total) * 100) : 0;

    if (total === 0 || percent === 0) {
        progressBar.classList.add('indeterminate');
        progressBar.style.width = '';
    } else {
        progressBar.classList.remove('indeterminate');
        progressBar.style.width = `${percent}%`;
    }

    percentage.textContent = `${percent}%`;
    statusEl.textContent = status;

    if (currentArtist) {
        artistEl.textContent = ` | 🔍 ${currentArtist}`;
    } else {
        artistEl.textContent = '';
    }

    if (current > 0 && total > 0 && current < total) {
        const elapsed = (Date.now() - progressStartTime) / 1000;
        const timePerItem = elapsed / current;
        const remaining = Math.round(timePerItem * (total - current));
        timeEl.textContent = ` | ⏱️ ~${remaining}s`;
    } else {
        timeEl.textContent = '';
    }
}

// Progress monitoring
let progressInterval = null;
let progressPollCount = 0;
const MAX_PROGRESS_POLLS = 120;

async function startProgressMonitoring(contextTitle = 'Generando Recomendaciones') {
    if (progressInterval) {
        clearInterval(progressInterval);
    }

    showProgressModal(contextTitle);
    progressPollCount = 0;

    progressInterval = setInterval(async () => {
        try {
            progressPollCount++;

            if (progressPollCount > MAX_PROGRESS_POLLS) {
                console.warn('Progress monitoring timed out');
                stopProgressMonitoring();
                hideProgressModal();
                alert('La operación está tardando más de lo esperado. Por favor, intenta de nuevo.');
                return;
            }

            const response = await fetch('/api/recommendations/progress');
            if (!response.ok) {
                console.error('Progress fetch failed:', response.status);
                return;
            }

            const progress = await response.json();

            if (progress.status === 'processing' && progress.total > 0) {
                const statusMsg = `Procesando artista ${progress.current} de ${progress.total}`;
                updateProgressUI(
                    progress.current,
                    progress.total,
                    statusMsg,
                    progress.current_artist || ''
                );
            } else if (progress.status === 'completed' || progress.status === 'idle') {
                stopProgressMonitoring();
            } else if (progress.status === 'error') {
                stopProgressMonitoring();
                hideProgressModal();
                alert('Hubo un error al procesar las recomendaciones. Por favor, intenta de nuevo.');
            }
        } catch (error) {
            console.error('Error fetching progress:', error);
        }
    }, 500);
}

function stopProgressMonitoring() {
    if (progressInterval) {
        clearInterval(progressInterval);
        progressInterval = null;
        progressPollCount = 0;
    }
}


// Load all recommendations from Last.fm
async function loadAllRecommendations() {
    showLoading(true, 'Cargando recomendaciones desde todas las fuentes...');

    try {
        const promises = [];

        if (hasLastfm) {
            const lastfmUsername = localStorage.getItem('lastfm_username');
            if (lastfmUsername) {
                promises.push(
                    fetch('/api/lastfm/recommendations', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ time_range: 'medium_term', username: lastfmUsername })
                    })
                        .then(res => res.json())
                        .then(data => {
                            const albums = data.albums || [];
                            albums.forEach(album => {
                                album.source = 'lastfm';
                            });
                            return { albums };
                        })
                        .catch(err => {
                            console.error('Last.fm recommendations failed:', err);
                            return { albums: [] };
                        })
                );
            } else {
                promises.push(Promise.resolve({ albums: [] }));
            }
        } else {
            promises.push(Promise.resolve({ albums: [] }));
        }

        const [lastfmData] = await Promise.all(promises);
        const lastfmAlbums = lastfmData.albums || [];

        if (lastfmAlbums.length === 0) {
            showLoading(false);
            alert('No se encontraron recomendaciones. Por favor, conecta al menos una fuente.');
            return;
        }

        // localStorage caching removed
        let finalRecs = lastfmAlbums;
        // localStorage.setItem('last_recommendations', JSON.stringify(finalRecs));
        // localStorage.setItem('last_updated', new Date().toISOString());

        // Save to database if user is logged in
        const userId = localStorage.getItem('userId');
        const lastfmUsername = localStorage.getItem('lastfm_username');

        if (userId && lastfmUsername) {
            try {
                // Save Last.fm profile snapshot (top artists)
                const topArtistsRes = await fetch('/api/lastfm/top-artists', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ time_range: 'medium_term', username: lastfmUsername })
                });

                if (topArtistsRes.ok) {
                    const topArtistsData = await topArtistsRes.json();
                    const topArtists = (topArtistsData.artists || []).slice(0, 20).map(a => ({
                        name: a.name,
                        playcount: a.playcount || 0
                    }));

                    // Save profile to DB
                    await fetch(`/users/${userId}/profile/lastfm`, {
                        method: 'PUT',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            lastfm_username: lastfmUsername,
                            top_artists: topArtists
                        })
                    });
                    console.log('✓ Last.fm profile saved to database');
                }

                // Save recommendations to DB
                const recsToSave = lastfmAlbums.slice(0, 50).map(rec => ({
                    artist_name: rec.artist_name || rec.artist,
                    album_title: rec.album_name || rec.album,
                    album_mbid: rec.mbid || null,
                    source: 'lastfm'
                }));

                if (recsToSave.length > 0) {
                    await fetch(`/users/${userId}/recommendations/regenerate`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ new_recs: recsToSave })
                    });
                    console.log(`✓ ${recsToSave.length} recommendations saved to database`);
                }
            } catch (e) {
                console.error('Error saving to database:', e);
                // Don't fail the whole flow if DB save fails
            }
        }

        if (userId) {
            console.log('Reloading mixed recommendations from DB...');
            await fetchUserRecommendations(userId);
        } else {
            renderRecommendations(finalRecs);
        }

    } catch (error) {
        console.error('Error loading all recommendations:', error);
        showLoading(false);
        alert('Error al cargar recomendaciones. Por favor, intenta de nuevo.');
    }
}

// Merge recommendation lists from multiple sources with deduplication
async function mergeRecommendationLists(lastfmAlbums, artistAlbums = []) {
    try {
        const response = await fetch('/api/recommendations/merge', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                lastfm_recommendations: lastfmAlbums,
                artist_recommendations: artistAlbums
            })
        });

        const data = await response.json();
        return data.recommendations || [];
    } catch (error) {
        console.error('Error merging recommendations:', error);
        return [...lastfmAlbums, ...artistAlbums];
    }
}

// Load mixed recommendations (artists only)
async function loadMixedRecommendations(artistNames) {
    startProgressMonitoring('Combinando Recomendaciones');

    try {
        const response = await fetch('/api/recommendations/artists', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                artist_names: artistNames
            })
        });

        const data = await response.json();

        stopProgressMonitoring();
        hideProgressModal();

        if (data.recommendations && data.recommendations.length > 0) {
            const formattedRecs = formatArtistRecommendations(data.recommendations);
        } else {
            alert('No se encontraron recomendaciones. Por favor, intenta de nuevo.');
        }
    } catch (error) {
        console.error('Error loading mixed recommendations:', error);
        stopProgressMonitoring();
        hideProgressModal();
        alert('Error al cargar recomendaciones. Por favor, intenta de nuevo.');
    }
}

let allRecommendations = [];
let currentFilter = 'all';
window.currentFilter = currentFilter; // Expose globally

// Render recommendations grid (fast, no pricing calls)
function renderRecommendations(recommendations) {
    allRecommendations = recommendations;
    // Keep album status map in sync (useful when recommendations are loaded from DB)
    syncAlbumStatusesFromRecs(recommendations);

    document.getElementById('landing-view').style.display = 'none';
    document.getElementById('album-detail-view').style.display = 'none';
    document.body.classList.remove('landing-active');
    document.getElementById('recommendations-view').classList.add('active');

    const hasArtistBased = recommendations.some(rec => rec.source === 'artist_based' || rec.source === 'manual');
    const hasLastfmBased = recommendations.some(rec => rec.source === 'lastfm');

    const artistSearchBtn = document.getElementById('artist-search-header-btn');
    const lastfmHeaderBtn = document.getElementById('lastfm-header-btn');
    const lastfmFilterBtn = document.querySelector('.filter-btn[data-filter="lastfm"]');

    if (lastfmFilterBtn) {
        lastfmFilterBtn.style.display = hasLastfmBased ? 'inline-block' : 'none';
    }

    if (hasArtistBased) {
        document.getElementById('last-updated').textContent = 'Basado en tus artistas seleccionados';
    } else {
        updateLastUpdatedText();
    }

    // Show artist search button always
    artistSearchBtn.style.display = 'inline-flex';

    // Show Last.fm button only if not connected
    const lastfmUsername = localStorage.getItem('lastfm_username');
    if (lastfmHeaderBtn) {
        const shouldHide = !!(lastfmUsername || window.lastfmConnected);
        console.log(`Render: Last.fm button visibility check. Username: ${lastfmUsername}, Connected: ${window.lastfmConnected} -> Hide: ${shouldHide}`);
        lastfmHeaderBtn.style.display = shouldHide ? 'none' : 'inline-flex';
    }

    const filterButtons = document.querySelectorAll('.filter-btn');
    if (filterButtons.length > 0) {
        filterButtons.forEach(btn => {
            btn.classList.remove('active');
        });
        const activeBtn = document.querySelector(`.filter-btn[data-filter="${currentFilter}"]`);
        if (activeBtn) {
            activeBtn.classList.add('active');
        }
    }

    let filtered;
    if (currentFilter === 'all') {
        // Exclude disliked and owned albums from "all" view
        // BUT allow 'owned' if it's a specific journey recommendation (e.g. Upgrade)
        filtered = allRecommendations.filter(rec => {
            const { artist, album } = getRecArtistAndAlbum(rec);
            const status = typeof window.getAlbumStatus === 'function' ? window.getAlbumStatus(artist, album) : null;

            if (status === 'disliked') {
                console.log(`[DEBUG] Hiding disliked item: ${artist} - ${album} (Source: ${rec.source})`);
                return false;
            }

            // Allow if it's an upgrade or completion recommendation, even if owned
            if (rec.source === 'collection_upgrade' || rec.source === 'discography_completion') {
                return true;
            }

            if (status === 'owned') {
                // Log only occasionally or it will flood, but for now we need it
                console.log(`[DEBUG] Hiding owned item: ${artist} - ${album} (Source: ${rec.source})`);
                return false;
            }
            return true;
        });
    } else if (currentFilter === 'favorites') {
        // Filter only favorites
        filtered = allRecommendations.filter(rec => {
            const { artist, album } = getRecArtistAndAlbum(rec);
            return typeof window.getAlbumStatus === 'function' && window.getAlbumStatus(artist, album) === 'favorite';
        });
    } else if (currentFilter === 'lastfm') {
        // Exclude disliked and owned from lastfm view
        filtered = allRecommendations.filter(rec => {
            const { artist, album } = getRecArtistAndAlbum(rec);
            const status = typeof window.getAlbumStatus === 'function' ? window.getAlbumStatus(artist, album) : null;
            return rec.source === 'lastfm' && status !== 'disliked' && status !== 'owned';
        });
    } else if (currentFilter === 'artists') {
        // Exclude disliked and owned from artists view
        filtered = allRecommendations.filter(rec => {
            const { artist, album } = getRecArtistAndAlbum(rec);
            const status = typeof window.getAlbumStatus === 'function' ? window.getAlbumStatus(artist, album) : null;
            return rec.source === 'manual' && status !== 'disliked' && status !== 'owned';
        });
    } else if (currentFilter === 'owned') {
        // Show only owned albums
        filtered = allRecommendations.filter(rec => {
            const { artist, album } = getRecArtistAndAlbum(rec);
            return typeof window.getAlbumStatus === 'function' && window.getAlbumStatus(artist, album) === 'owned';
        });
    } else if (currentFilter === 'disliked') {
        // Show only disliked albums
        filtered = allRecommendations.filter(rec => {
            const { artist, album } = getRecArtistAndAlbum(rec);
            return typeof window.getAlbumStatus === 'function' && window.getAlbumStatus(artist, album) === 'disliked';
        });
    } else {
        filtered = allRecommendations;
    }

    displayFilteredRecommendations(filtered);

    // Load profile sidebar
    if (typeof loadProfileSidebar === 'function') {
        loadProfileSidebar();
    }

    showLoading(false);
}

function displayFilteredRecommendations(recommendations) {
    const container = document.getElementById('albums-container');
    container.innerHTML = '';

    recommendations.forEach(rec => {
        const card = createAlbumCard(rec);
        container.appendChild(card);
    });
}

function filterRecommendations(filter) {
    currentFilter = filter;
    window.currentFilter = filter; // Sync global

    document.querySelectorAll('.filter-btn').forEach(btn => {
        btn.classList.remove('active');
    });
    document.querySelector(`.filter-btn[data-filter="${filter}"]`).classList.add('active');

    let filtered;
    if (filter === 'all') {
        // Exclude disliked and owned albums from "all" view
        // BUT allow 'owned' if it's a specific journey recommendation (e.g. Upgrade)
        filtered = allRecommendations.filter(rec => {
            const { artist, album } = getRecArtistAndAlbum(rec);
            const status = typeof window.getAlbumStatus === 'function' ? window.getAlbumStatus(artist, album) : null;

            if (status === 'disliked') return false;

            // Allow if it's an upgrade or completion recommendation, even if owned
            if (rec.source === 'collection_upgrade' || rec.source === 'discography_completion') {
                return true;
            }

            return status !== 'owned';
        });
    } else if (filter === 'lastfm') {
        // Exclude disliked and owned from lastfm view
        filtered = allRecommendations.filter(rec => {
            const { artist, album } = getRecArtistAndAlbum(rec);
            const status = typeof window.getAlbumStatus === 'function' ? window.getAlbumStatus(artist, album) : null;
            return rec.source === 'lastfm' && status !== 'disliked' && status !== 'owned';
        });
    } else if (filter === 'artists') {
        // Exclude disliked and owned from artists view
        filtered = allRecommendations.filter(rec => {
            const { artist, album } = getRecArtistAndAlbum(rec);
            const status = typeof window.getAlbumStatus === 'function' ? window.getAlbumStatus(artist, album) : null;
            return rec.source === 'manual' && status !== 'disliked' && status !== 'owned';
        });
    } else if (filter === 'favorites') {
        filtered = allRecommendations.filter(rec => {
            const { artist, album } = getRecArtistAndAlbum(rec);
            return typeof window.getAlbumStatus === 'function' &&
                window.getAlbumStatus(artist, album) === 'favorite';
        });
    } else if (filter === 'owned') {
        // Show only owned albums
        filtered = allRecommendations.filter(rec => {
            const { artist, album } = getRecArtistAndAlbum(rec);
            return typeof window.getAlbumStatus === 'function' &&
                window.getAlbumStatus(artist, album) === 'owned';
        });
    } else if (filter === 'disliked') {
        // Show only disliked albums
        filtered = allRecommendations.filter(rec => {
            const { artist, album } = getRecArtistAndAlbum(rec);
            return typeof window.getAlbumStatus === 'function' &&
                window.getAlbumStatus(artist, album) === 'disliked';
        });
    }

    displayFilteredRecommendations(filtered);
}
window.filterRecommendations = filterRecommendations; // Expose globally

// Create album card (no pricing data yet)
function createAlbumCard(rec) {
    // Use helper to get consistent names
    const { artist, album } = getRecArtistAndAlbum(rec);

    // Handle cover images
    // Check for various image properties and ensure it's not an empty string
    let cover = rec.cover_url || rec.image_url || rec.image;

    // If cover is missing or is a generic Last.fm placeholder (often empty or just a star), use our SVG
    if (!cover || cover.includes('2a96cbd8b46e442fc41c2b86b821562f')) {
        cover = 'data:image/svg+xml,%3Csvg xmlns="http://www.w3.org/2000/svg" width="300" height="300"%3E%3Crect fill="%23f0f0f0" width="300" height="300"/%3E%3Ctext fill="%23888" font-family="sans-serif" font-size="24" dy="8" font-weight="bold" x="50%25" y="50%25" text-anchor="middle"%3EVinylbe%3C/text%3E%3C/svg%3E';
    }

    const card = document.createElement('div');
    card.className = 'album-card';

    // Check status
    let currentStatus = null;
    if (typeof window.getAlbumStatus === 'function') {
        currentStatus = window.getAlbumStatus(artist, album);
        console.log(`[DEBUG createAlbumCard] artist="${artist}", album="${album}", currentStatus="${currentStatus}"`);
    } else {
        console.error('[DEBUG createAlbumCard] window.getAlbumStatus is not a function!');
    }

    card.innerHTML = `
        <div class="album-cover">
            <img src="${cover}" alt="${album}" loading="lazy">
            ${rec.is_partial ? '<div class="partial-badge" title="Información pendiente de enriquecer">⏳</div>' : ''}
            ${rec.source === 'collection_upgrade' ? '<div class="upgrade-badge" title="Upgrade recomendado">UPGRADE ⬆</div>' : ''}
            ${rec.source === 'discography_completion' ? '<div class="completion-badge" title="Completar discografía">COMPLETAR</div>' : ''}
        </div>
        <div class="album-info">
            <h3>${album}</h3>
            <p>${artist}</p>
            ${rec.source === 'collection_upgrade' && rec.current_formats ?
            `<p class="upgrade-info">Tienes: <span class="format-tag">${rec.current_formats.join(', ')}</span></p>` : ''}
            ${rec.source === 'discography_completion' ?
            `<p class="completion-info">Falta en tu colección</p>` : ''}
            <div class="album-actions">
                <button class="action-btn favorite ${currentStatus === 'favorite' ? 'active' : ''}" title="Guardar en favoritos" data-action="favorite">★</button>
                <button class="action-btn owned ${currentStatus === 'owned' ? 'active' : ''}" title="Ya lo tengo" data-action="owned">✓</button>
                <button class="action-btn disliked ${currentStatus === 'disliked' ? 'active' : ''}" title="No me interesa" data-action="disliked">✗</button>
            </div>
        </div>
    `;

    // Add event listeners to buttons
    card.querySelectorAll('.action-btn').forEach(btn => {
        btn.addEventListener('click', async (e) => {
            e.stopPropagation(); // Prevent card click
            const action = btn.dataset.action;

            if (typeof window.setAlbumStatus === 'function') {
                // Optimistic UI update
                const isActive = btn.classList.contains('active');

                // Reset all buttons in this card
                card.querySelectorAll('.action-btn').forEach(b => b.classList.remove('active'));

                let newStatus = action;
                if (isActive) {
                    // Toggle off
                    newStatus = null;
                } else {
                    // Toggle on
                    btn.classList.add('active');
                }

                console.log(`Setting status: ${artist} - ${album} -> ${newStatus}`);

                console.log(`Action: ${action}, NewStatus: ${newStatus}, Filter: ${currentFilter}`);

                // Immediate visual feedback: hide card if marking as owned/disliked in "all" view
                const shouldHideImmediately = (newStatus === 'owned' || newStatus === 'disliked') &&
                    (currentFilter === 'all' ||
                        currentFilter === 'lastfm' ||
                        currentFilter === 'artists');

                console.log(`Should hide immediately: ${shouldHideImmediately}`);

                if (shouldHideImmediately) {
                    // Animate out immediately
                    card.style.transition = 'opacity 0.3s ease, transform 0.3s ease';
                    card.style.opacity = '0';
                    card.style.transform = 'scale(0.9)';

                    // Remove from DOM after animation (independent of backend call)
                    setTimeout(() => {
                        card.remove();
                    }, 300);

                    // Call global handler with skipRender=true to update DB in background
                    window.setAlbumStatus(artist, album, newStatus, rec.id, true).catch(e => {
                        console.error('Error updating status in background:', e);
                    });
                } else {
                    // Normal update (favorites, or toggling off in special views)
                    await window.setAlbumStatus(artist, album, newStatus, rec.id, false);
                }
            } else {
                console.error('setAlbumStatus function not available');
            }
        });
    });

    card.addEventListener('click', () => {
        openAlbumDetail(rec);
    });

    return card;
}

// Open album detail page
async function openAlbumDetail(rec) {
    let artist, album, cover;

    // Check for direct properties first (used by DB-stored recs: manual, lastfm, mixed, etc.)
    if (rec.artist_name || rec.album_name) {
        artist = rec.artist_name || 'Unknown Artist';
        album = rec.album_name || 'Unknown Album';
        cover = rec.cover_url || rec.image_url || 'data:image/svg+xml,%3Csvg xmlns="http://www.w3.org/2000/svg" width="300" height="300"%3E%3Crect fill="%23ddd" width="300" height="300"/%3E%3Ctext fill="%23999" font-family="sans-serif" font-size="18" dy="10.5" font-weight="bold" x="50%25" y="50%25" text-anchor="middle"%3ENo Cover%3C/text%3E%3C/svg%3E';

    } else {
        const albumInfo = rec.album_info || {};
        artist = albumInfo.artists?.[0]?.name || 'Unknown Artist';
        album = albumInfo.name || 'Unknown Album';
        cover = albumInfo.images?.[0]?.url || 'data:image/svg+xml,%3Csvg xmlns="http://www.w3.org/2000/svg" width="300" height="300"%3E%3Crect fill="%23ddd" width="300" height="300"/%3E%3Ctext fill="%23999" font-family="sans-serif" font-size="18" dy="10.5" font-weight="bold" x="50%25" y="50%25" text-anchor="middle"%3ENo Cover%3C/text%3E%3C/svg%3E';
    }


    document.getElementById('recommendations-view').style.display = 'none';
    document.getElementById('album-detail-view').style.display = 'block';

    document.getElementById('detail-cover').src = cover;
    document.getElementById('detail-title').textContent = album;
    document.getElementById('detail-artist').textContent = artist;

    const pricingContainer = document.getElementById('detail-pricing');
    pricingContainer.innerHTML = `
        <div class="spinner-small"></div>
        <p style="text-align: center; color: var(--text-secondary); margin-top: 1rem;">Cargando información...</p>
    `;

    try {
        const pricingData = await fetchPricing(artist, album);
        pricingContainer.innerHTML = renderDetailPricing(pricingData);
    } catch (error) {
        console.error('Error fetching pricing:', error);
        pricingContainer.innerHTML = '<p class="error-text">No se pudo cargar la información</p>';
    }
}

// Go back to recommendations
function backToRecommendations() {
    document.getElementById('album-detail-view').style.display = 'none';
    document.getElementById('recommendations-view').style.display = 'block';
}

// Render pricing in detail view
function renderDetailPricing(pricing) {
    let html = '';

    // 1. Spotify link
    if (pricing.spotify_id) {
        html += `
            <a href="https://open.spotify.com/album/${pricing.spotify_id}" target="_blank" class="btn-spotify">
                <svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" fill="currentColor">
                    <path d="M12 0C5.4 0 0 5.4 0 12s5.4 12 12 12 12-5.4 12-12S18.66 0 12 0zm5.521 17.34c-.24.359-.66.48-1.021.24-2.82-1.74-6.36-2.101-10.561-1.141-.418.122-.779-.179-.899-.539-.12-.421.18-.78.54-.9 4.56-1.021 8.52-.6 11.64 1.32.42.18.479.659.301 1.02zm1.44-3.3c-.301.42-.841.6-1.262.3-3.239-1.98-8.159-2.58-11.939-1.38-.479.12-1.02-.12-1.14-.6-.12-.48.12-1.021.6-1.141C9.6 9.9 15 10.561 18.72 12.84c.361.181.54.78.241 1.2zm.12-3.36C15.24 8.4 8.82 8.16 5.16 9.301c-.6.179-1.2-.181-1.38-.721-.18-.601.18-1.2.72-1.381 4.26-1.26 11.28-1.02 15.721 1.621.539.3.719 1.02.419 1.56-.299.421-1.02.599-1.559.3z"/>
                </svg>
                PLAY ON SPOTIFY
            </a>
        `;
    }

    // 2. UNIFIED PRICE LIST (Local Stores + eBay)
    let priceItems = [];

    // Add Local Stores
    if (pricing.local_stores && typeof pricing.local_stores === 'object') {
        const storeLogos = {
            'marilians': '/static/img/marilians_logo.png',
            'bajo_el_volcan': '/static/img/bajo_el_volcan_logo.png',
            'bora_bora': '/static/img/bora_bora_logo.png',
            'revolver': null // Pending logo
        };
        const storeNiceNames = {
            'marilians': 'Marilians',
            'bajo_el_volcan': 'Bajo el Volcán',
            'bora_bora': 'Bora Bora',
            'revolver': 'Revolver Records'
        };

        Object.entries(pricing.local_stores).forEach(([key, data]) => {
            if (typeof data === 'object' && data !== null && data.price !== null) {
                priceItems.push({
                    type: 'local',
                    name: storeNiceNames[key] || key,
                    logo: storeLogos[key],
                    price: data.price,
                    url: data.url,
                    availability: data.availability,  // Add availability
                    sortPrice: data.price
                });
            }
        });
    }

    // Add eBay
    if (pricing.ebay_offer) {
        // Parse "35.00 EUR" -> 35.00
        const priceStr = String(pricing.ebay_offer.total_price || '0');
        const priceVal = parseFloat(priceStr.replace(/[^\d.]/g, ''));

        priceItems.push({
            type: 'ebay',
            name: 'eBay',
            logo: '/static/img/ebay_logo.png', // New uploaded logo
            price: pricing.ebay_offer.total_price,
            url: pricing.ebay_offer.url,
            sortPrice: priceVal
        });
    }

    // Sort by price (cheapest first)
    priceItems.sort((a, b) => a.sortPrice - b.sortPrice);

    if (priceItems.length > 0) {
        html += '<div class="price-list-container"><h3>Comparativa de Precios</h3><div class="price-list">';

        priceItems.forEach(item => {
            const priceDisplay = typeof item.price === 'number' ? `${item.price.toFixed(2)} EUR` : item.price;

            let logoHtml = '';
            if (item.logo) {
                logoHtml = `<img src="${item.logo}" alt="${item.name}" class="store-logo">`;
            } else {
                logoHtml = `<div class="store-logo-placeholder"><span>${item.name.substring(0, 2).toUpperCase()}</span></div>`;
            }

            let availabilityHtml = '';
            if (item.availability && item.availability === 'Consultar disponibilidad') {
                availabilityHtml = `<span style="font-size: 0.7em; background: #ffc107; color: #333; padding: 2px 5px; border-radius: 4px; margin-right: 5px; white-space: nowrap;">Consultar disp.</span>`;
            }

            // Entire card is now the anchor tag
            html += `
                <a href="${item.url}" target="_blank" class="price-item-link">
                    <div class="price-item-logo">
                        ${logoHtml}
                    </div>
                    <div class="price-item-info">
                        <span class="store-name">${item.name}</span>
                    </div>
                    <div class="price-item-value">
                        ${availabilityHtml}
                        <span class="price-tag">${priceDisplay}</span>
                        <svg class="chevron-right" viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" stroke-width="2" fill="none">
                            <polyline points="9 18 15 12 9 6"></polyline>
                        </svg>
                    </div>
                </a>
            `;
        });
        html += '</div></div>';
    } else {
        html += `<div class="info-message">ℹ️ No hay precios disponibles actualmente</div>`;
    }

    // 3. Discogs marketplace link
    if (pricing.discogs_sell_url) {
        html += `
            <a href="${pricing.discogs_sell_url}" target="_blank" class="btn-secondary btn-discogs-market">
                🎵 Buscar en Discogs Marketplace
            </a>
        `;
    }

    // 4. Tracklist section (No scroll)
    if (pricing.tracklist && pricing.tracklist.length > 0) {
        html += '<div class="tracklist-section"><h3>Lista de Canciones</h3><ul class="tracklist no-scroll">';
        pricing.tracklist.forEach(track => {
            const duration = track.duration ? ` <span class="duration">${track.duration}</span>` : '';
            html += `<li><span>${track.title}</span>${duration}</li>`;
        });
        html += '</ul></div>';
    }

    // 5. Discogs detail link
    if (pricing.discogs_url) {
        html += `
            <a href="${pricing.discogs_url}" target="_blank" class="btn-secondary btn-discogs-release">
                📖 Ver Ficha en Discogs
            </a>
        `;
    }



    // Trigger Lazy Load for FNAC (if not already present and if container/artist exists)
    // DISABLED per user request
    /*
    if (pricing.artist && pricing.album && document.getElementById('detail-pricing')) {
        setTimeout(() => {
            fetchFnacPrice(pricing.artist, pricing.album);
        }, 500); // Small delay to allow main render to finish
    }
    */

    return html;
}

// Fetch pricing for an album
async function fetchPricing(artist, album) {
    // Note: This now calls the endpoint that excludes FNAC by default for speed
    const response = await fetch(`/album-pricing?artist=${encodeURIComponent(artist)}&album=${encodeURIComponent(album)}`);
    if (!response.ok) {
        throw new Error('Failed to fetch pricing');
    }
    return await response.json();
}

// Lazy load FNAC pricing
async function fetchFnacPrice(artist, album) {
    console.log('Lazy loading FNAC price...');
    try {
        const response = await fetch(`/api/pricing/fnac?artist=${encodeURIComponent(artist)}&album=${encodeURIComponent(album)}`);
        const data = await response.json();

        if (data && data.fnac && data.fnac.price) {
            console.log('FNAC price found:', data.fnac);

            // Find the price list container
            const priceList = document.querySelector('.price-list');

            if (priceList) {
                // Create FNAC item HTML
                const fnacUrl = data.fnac.url;
                const fnacPrice = typeof data.fnac.price === 'number' ? `${data.fnac.price.toFixed(2)} EUR` : data.fnac.price;

                const fnacHtml = `
                <a href="${fnacUrl}" target="_blank" class="price-item-link price-item-fnac-new" style="opacity: 0; transition: opacity 0.5s;">
                    <div class="price-item-logo">
                        <img src="/static/img/fnac_logo.png" alt="FNAC" class="store-logo">
                    </div>
                    <div class="price-item-info">
                        <span class="store-name">FNAC</span>
                        <span class="badge-new" style="font-size: 0.7em; background: #28a745; color: white; padding: 2px 5px; border-radius: 4px; margin-left: 5px;">Nuevo</span>
                    </div>
                    <div class="price-item-value">
                        <span class="price-tag">${fnacPrice}</span>
                        <svg class="chevron-right" viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" stroke-width="2" fill="none">
                            <polyline points="9 18 15 12 9 6"></polyline>
                        </svg>
                    </div>
                </a>
                `;

                // Append and animate
                const tempDiv = document.createElement('div');
                tempDiv.innerHTML = fnacHtml.trim();
                const newLink = tempDiv.firstChild;
                priceList.appendChild(newLink);

                // Trigger reflow
                newLink.offsetHeight;
                newLink.style.opacity = '1';

            } else {
                // If no price list exists (no other stores found), we might need to create the container
                // For now, simple logging, as usually at least eBay or something exists.
                // If absolutely nothing exists, we'd need to replace the "No prices" message.
                const container = document.querySelector('.info-message');
                if (container && container.textContent.includes('No hay precios')) {
                    // Replace empty message with price list
                    const detailContainer = document.getElementById('detail-pricing');
                    // We would ideally re-use render logic, but manual construction is safer/quicker here
                    // to avoiding circular dependencies or complex re-renders.
                    if (detailContainer) {
                        // Simple reload might be easiest if we went from 0 to 1 result
                        // detailContainer.innerHTML = renderDetailPricing({...currentPricing, local_stores: {fnac: data.fnac}});
                    }
                }
            }
        } else {
            console.log('No FNAC price found via lazy load.');
        }
    } catch (error) {
        console.warn('Failed to lazy load FNAC:', error);
    }
}

// Update last updated text
function updateLastUpdatedText() {
    const lastUpdated = localStorage.getItem('last_updated');
    if (lastUpdated) {
        const date = new Date(lastUpdated);
        const now = new Date();
        const diffMs = now - date;
        const diffHours = Math.floor(diffMs / (1000 * 60 * 60));
        const diffMins = Math.floor(diffMs / (1000 * 60));

        let timeText = '';
        if (diffHours > 0) {
            timeText = `Actualizado hace ${diffHours} hora${diffHours > 1 ? 's' : ''}`;
        } else if (diffMins > 0) {
            timeText = `Actualizado hace ${diffMins} minuto${diffMins > 1 ? 's' : ''}`;
        } else {
            timeText = 'Actualizado hace un momento';
        }

        document.getElementById('last-updated').textContent = `Basado en tu escucha. ${timeText}`;
    }
}

// Check if user has cached recommendations
function checkCachedRecommendations() {
    const cached = localStorage.getItem('last_recommendations');

    if (cached) {
        const recommendations = JSON.parse(cached);

        // Auto-fix: ensure all recommendations have source='manual' for filtering
        let needsFix = false;
        recommendations.forEach(rec => {
            if (rec.source !== 'manual') {
                rec.source = 'manual';
                needsFix = true;
            }
        });

        // Save back if we fixed any
        if (needsFix) {
            console.log('✓ Auto-fixed source field for cached recommendations');
            localStorage.setItem('last_recommendations', JSON.stringify(recommendations));
        }

        renderRecommendations(recommendations);
    }
}

// Artist Search Modal
let artistSearchComponent = null;

async function openArtistSearch(initialQuery) {
    const modal = document.getElementById('artist-search-modal');
    modal.classList.add('active');
    document.body.style.overflow = 'hidden';

    if (!artistSearchComponent) {
        artistSearchComponent = new ArtistSearch('artist-search-container', {
            minArtists: 1,
            maxArtists: 10,
            onContinue: handleArtistSelection
        });

        // Load selected artists from DB (logged-in users) or localStorage (guest users)
        const userId = localStorage.getItem('userId');
        if (userId) {
            try {
                const res = await fetch(`/api/users/${userId}/selected-artists`);
                if (res.ok) {
                    const dbArtists = await res.json();
                    const artistNames = dbArtists.map(a => a.artist_name);
                    console.log(`✓ Restoring ${artistNames.length} artists from DB:`, artistNames);
                    artistSearchComponent.restoreArtists(artistNames);
                }
            } catch (e) {
                console.error('Error loading selected artists:', e);
            }
        } else {
            // Guest user: Load from localStorage
            try {
                const storedArtists = localStorage.getItem('selected_artist_names');
                if (storedArtists) {
                    const artistNames = JSON.parse(storedArtists);
                    if (Array.isArray(artistNames) && artistNames.length > 0) {
                        console.log(`✓ Restoring ${artistNames.length} artists from localStorage (guest):`, artistNames);
                        artistSearchComponent.restoreArtists(artistNames);
                    }
                }
            } catch (e) {
                console.error('Error loading selected artists from localStorage:', e);
            }
        }
    }

    // Pre-fill the modal search input and trigger a search if initialQuery provided
    if (initialQuery && initialQuery.trim().length > 0) {
        const searchInput = document.getElementById('artist-search-input');
        if (searchInput && searchInput.value !== initialQuery) {
            searchInput.value = initialQuery;
            // Show the clear button
            const clearBtn = document.getElementById('clear-search-btn');
            if (clearBtn) clearBtn.style.display = 'block';
            // Trigger search immediately
            if (initialQuery.trim().length >= 2) {
                artistSearchComponent.performSearch(initialQuery.trim());
            }
        }
    }
}

function closeArtistSearch() {
    const modal = document.getElementById('artist-search-modal');
    modal.classList.remove('active');
    document.body.style.overflow = '';
}

async function handleArtistSelection(selectedArtists, searchComponent) {
    const userId = localStorage.getItem('userId');
    console.log('handleArtistSelection called with', selectedArtists.length, 'artists. User:', userId);

    // Use passed component or fallback to global (for backward compatibility)
    const component = searchComponent || artistSearchComponent;

    // Sync with database (artists)
    if (userId) {
        try {
            // 1. Get current DB artists
            const res = await fetch(`/api/users/${userId}/selected-artists`);
            if (res.ok) {
                const dbArtists = await res.json();
                const dbArtistNames = new Set(dbArtists.map(a => a.artist_name));
                const selectedNames = new Set(selectedArtists.map(a => a.name));

                // 2. Add new ones
                for (const artist of selectedArtists) {
                    if (!dbArtistNames.has(artist.name)) {
                        console.log(`Adding artist to DB: ${artist.name}`);
                        const addResp = await fetch(`/api/users/${userId}/selected-artists`, {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({
                                artist_name: artist.name,
                                mbid: artist.mbid || null,
                                source: 'manual'
                            })
                        });

                        if (addResp.ok) {
                            console.log(`✓ Added artist to DB: ${artist.name}`);
                        } else {
                            console.error(`✗ Failed to add artist ${artist.name}:`, addResp.status);
                        }
                    }
                }

                // 3. Remove deleted ones
                for (const dbArtist of dbArtists) {
                    if (!selectedNames.has(dbArtist.artist_name)) {
                        console.log(`Removing artist from DB: ${dbArtist.artist_name}`);
                        const delResp = await fetch(`/api/users/${userId}/selected-artists/${dbArtist.id}`, {
                            method: 'DELETE'
                        });

                        if (delResp.ok) {
                            console.log(`✓ Removed artist from DB: ${dbArtist.artist_name}`);
                        } else {
                            console.error(`✗ Failed to remove artist ${dbArtist.artist_name}:`, delResp.status);
                        }
                    }
                }
            }
        } catch (e) {
            console.error('Error syncing artists with DB:', e);
        }

        // Refresh sidebar to show newly added artists
        if (typeof loadProfileSidebar === 'function') {
            loadProfileSidebar();
        }
    } else {
        // Guest user: also refresh sidebar
        if (typeof loadProfileSidebar === 'function') {
            loadProfileSidebar();
        }
    }

    const artistNames = selectedArtists.map(a => a.name);
    // localStorage caching for artists restored for guest sync
    localStorage.setItem('selected_artist_names', JSON.stringify(artistNames));


    if (!component) {
        console.error('Artist search component not available');
        closeArtistSearch();
        alert('Error: el componente de búsqueda no está disponible. Por favor, intenta de nuevo.');
        return;
    }

    // If no artists selected (only albums), skip recommendation generation
    if (artistNames.length === 0) {
        console.log('No artists selected, skipping recommendation generation');
        closeArtistSearch();
        if (userId) {
            await fetchUserRecommendations(userId);
        }
        return;
    }

    if (component.pendingPromises.size > 0) {
        console.log(`⏳ Waiting for ${component.pendingPromises.size} pending recommendations...`);
        showLoading(true, 'Finalizando recomendaciones...');
        await component.waitForAllPendingRecommendations();
        showLoading(false);
    }

    closeArtistSearch();

    const loadingStatus = component.getLoadingStatus();
    const cachedRecs = component.getCachedRecommendations();

    console.log(`Cache status: ${cachedRecs.length} recommendations, ${loadingStatus.success}/${loadingStatus.total} successful, ${loadingStatus.error} errors`);

    let finalRecs = [];

    // Strategy: Use cached recommendations if available, otherwise fetch from backend
    if (cachedRecs.length > 0) {
        console.log('✓ Using cached artist recommendations');
        finalRecs = formatArtistRecommendations(cachedRecs);
    } else {
        console.log('⚠ No cached recommendations, falling back to backend generation');
        const title = 'Generando Recomendaciones';
        startProgressMonitoring(title);

        try {
            const response = await fetch('/api/recommendations/artists', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ artist_names: artistNames })
            });
            const data = await response.json();
            stopProgressMonitoring();
            hideProgressModal();

            if (data.recommendations && data.recommendations.length > 0) {
                finalRecs = formatArtistRecommendations(data.recommendations);
            }
        } catch (error) {
            console.error('Error loading artist recommendations:', error);
            stopProgressMonitoring();
            hideProgressModal();
            alert('Error al cargar recomendaciones. Por favor, intenta de nuevo.');
            return;
        }
    }

    // Force source='manual' on all recommendations to ensure they appear in the artist filter
    if (finalRecs.length > 0) {
        finalRecs.forEach(rec => {
            rec.source = 'manual';
        });
    }

    if (finalRecs.length === 0) {
        alert('No se encontraron recomendaciones para estos artistas.');
        return;
    }

    // Save recommendations to DB if user is logged in
    if (userId) {
        try {
            console.log(`Saving ${finalRecs.length} recommendations to database for user ${userId}...`);
            const saveResp = await fetch(`/users/${userId}/recommendations/regenerate`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ new_recs: finalRecs })
            });

            if (saveResp.ok) {
                console.log('✓ Recommendations saved successfully to DB');
                if (typeof showToast === 'function') {
                    showToast('Recomendaciones guardadas correctamente', 'success');
                }
            } else {
                console.error('✗ Failed to save recommendations:', saveResp.status, await saveResp.text());
                if (typeof showToast === 'function') {
                    showToast('Error al guardar recomendaciones', 'error');
                }
            }

            // Reload from DB to ensure consistency (and get IDs, favorites, etc.)
            await fetchUserRecommendations(userId);

        } catch (e) {
            console.error('Error saving recommendations to DB:', e);
            // Fallback to local rendering if DB save fails
            // Fallback removed
            // localStorage.setItem('last_recommendations', JSON.stringify(finalRecs));
            // localStorage.setItem('last_updated', new Date().toISOString());
            renderRecommendations(finalRecs);
        }
    } else {
        // Guest user: merge with existing localStorage recommendations
        try {
            const existingRecs = localStorage.getItem('last_recommendations');
            let mergedRecs = [...finalRecs];

            if (existingRecs) {
                const existing = JSON.parse(existingRecs);
                console.log(`Found ${existing.length} existing recommendations in localStorage`);

                // Create a map of new recs by key for deduplication
                const newRecsMap = new Map();
                finalRecs.forEach(rec => {
                    const key = `${rec.artist_name}::${rec.album_name || rec.album_title}`;
                    newRecsMap.set(key, rec);
                });

                // Add existing recs that aren't in the new set
                // IMPORTANT: Ensure all existing recs also have source='manual'
                existing.forEach(rec => {
                    const key = `${rec.artist_name}::${rec.album_name || rec.album_title}`;
                    if (!newRecsMap.has(key)) {
                        // Ensure source is set to 'manual' for filtering
                        rec.source = 'manual';
                        mergedRecs.push(rec);
                    }
                });

                console.log(`Merged: ${finalRecs.length} new + ${existing.length} existing = ${mergedRecs.length} total`);
            }

            localStorage.setItem('last_recommendations', JSON.stringify(mergedRecs));
            localStorage.setItem('last_updated', new Date().toISOString());
            renderRecommendations(mergedRecs);
        } catch (e) {
            console.error('Error merging recommendations:', e);
            // Fallback to just saving new ones
            localStorage.setItem('last_recommendations', JSON.stringify(finalRecs));
            localStorage.setItem('last_updated', new Date().toISOString());
            renderRecommendations(finalRecs);
        }
    }
}

function formatArtistRecommendations(recommendations) {
    return recommendations.map(rec => {
        if (rec.source === 'artist_based' || rec.source === 'spotify') {
            return {
                album_name: rec.album_name,
                artist_name: rec.artist_name,
                image_url: rec.image_url,
                discogs_master_id: rec.discogs_master_id,
                rating: rec.rating,
                votes: rec.votes,
                year: rec.year,
                is_partial: rec.is_partial, // Preserve is_partial flag
                source: 'manual'  // Map to 'manual' for DB constraint
            };
        }
        return rec;
    });
}

function updateProfileUI(userId) {
    if (!userId) return;

    // Update connection buttons
    fetch(`/user/${userId}/connections`)
        .then(res => res.json())
        .then(conns => {
            const discogsBtn = document.getElementById('btn-conn-discogs');
            const discogsStatus = document.querySelector('#conn-discogs .conn-status');
            const discogsCard = document.getElementById('journey-config-card');

            if (conns.discogs && conns.discogs.connected) {
                if (discogsBtn) discogsBtn.style.display = 'none';
                if (discogsStatus) {
                    discogsStatus.textContent = 'Conectado como ' + (conns.discogs.username_text || conns.discogs.username);
                    discogsStatus.style.color = 'var(--success-color)';
                }
                if (discogsCard) discogsCard.style.display = 'block';
            }

            const lastfmBtn = document.getElementById('btn-conn-lastfm');
            const lastfmStatus = document.querySelector('#conn-lastfm .conn-status');

            if (conns.lastfm && conns.lastfm.connected) {
                if (lastfmBtn) lastfmBtn.style.display = 'none';
                if (lastfmStatus) {
                    lastfmStatus.textContent = 'Conectado como ' + (conns.lastfm.username);
                    lastfmStatus.style.color = 'var(--success-color)';
                }
            }
        })
        .catch(err => console.warn('Error fetching connections:', err));
}

// Initialize
// Initialize
document.addEventListener('DOMContentLoaded', async () => {
    loadMosaic();
    initTheme();

    if (typeof DiscogsWizard !== 'undefined') {
        DiscogsWizard.init();
    }

    checkDiscogsAuthReturn();

    // IMMEDIATELY hide Last.fm button if we can detect connection
    const quickCheckBtn = document.getElementById('lastfm-header-btn');
    const quickUsername = localStorage.getItem('lastfm_username');
    if (quickCheckBtn && quickUsername) {
        console.log('🚀 Quick hide: Found username in localStorage:', quickUsername);
        quickCheckBtn.style.display = 'none';
    }

    // Check if we just returned from Last.fm authentication
    checkLastfmAuthReturn();

    const userId = localStorage.getItem('userId');
    console.log('[DEBUG] App Start. Found userId:', userId);

    if (userId) {
        console.log('[DEBUG] Calling updateProfileUI with userId:', userId);
        updateProfileUI(userId);
    }

    handleLastfmCallback();


    // If user is logged in, load fresh recommendations from DB
    const lastfmUsername = localStorage.getItem('lastfm_username'); // Ensure we have this

    if (userId) {
        console.log(`🚀 Usuario detectado: ${userId}. Iniciando carga de recomendaciones...`);

        // Sync Last.fm profile first to ensure UI state is correct before rendering
        try {
            const profileResp = await fetch(`/api/users/${userId}/profile/lastfm`);
            if (profileResp.ok) {
                const profile = await profileResp.json();
                if (profile.lastfm_username) {
                    console.log('✓ Synced Last.fm username from backend (in DOMContentLoaded):', profile.lastfm_username);
                    localStorage.setItem('lastfm_username', profile.lastfm_username);
                    window.lastfmConnected = true; // Backup flag

                    // Force hide the button immediately
                    const btn = document.getElementById('lastfm-header-btn');
                    if (btn) {
                        console.log('Hiding Last.fm button immediately');
                        btn.style.display = 'none';
                    }

                    // Reload sidebar now that we have the username
                    if (typeof loadProfileSidebar === 'function') {
                        console.log('Reloading sidebar with synced profile...');
                        loadProfileSidebar();
                    }
                }
            }
        } catch (e) {
            console.warn('Error syncing Last.fm profile:', e);
        }

        // 1. Try to fetch existing recommendations
        try {
            await fetchUserRecommendations(userId);

            // 2. Check if we actually got anything. If not, and we have a username, force generation.
            const container = document.getElementById('albums-container');
            const updatedLastfmUsername = localStorage.getItem('lastfm_username'); // Get fresh value
            if ((!container || container.children.length === 0) && updatedLastfmUsername) {
                console.log('⚠️ No hay recomendaciones visibles. Forzando generación inicial...');
                await generateAndSaveRecommendations(userId, updatedLastfmUsername);
            }
        } catch (e) {
            console.error('Error en carga inicial:', e);
        }
    } else {
        // No user yet, keep any cached recommendations
        checkCachedRecommendations();
    }
});

// Listener for Discogs Auth Popup
window.addEventListener('message', function (event) {
    if (event.data.type === 'DISCOGS_AUTH_SUCCESS') {
        const payload = event.data.payload;
        localStorage.setItem('userId', payload.user_id);
        localStorage.setItem('discogs_username', payload.username);
        // Set flag for wizard
        localStorage.setItem('vinilogy_discogs_auth_completed', 'true');

        // Reload main window to trigger initialization and Wizard
        window.location.reload();
    }
});
